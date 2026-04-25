import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .automation import AutomationEngine
from .chrome_manager import (
    build_launch_command,
    close_pid,
    delete_profile_dir,
    detect_chrome_path,
    launch_chrome,
    pid_is_running,
    profile_data_dir,
    resolve_url,
    slugify_profile_id,
)
from .config_store import LabConfigStore
from .defaults import legacy_metadata_for_display
from .paths import CHROME_DATA_DIR
from .projects import get_adapter, list_adapters
from .run_history import prune_run_history
from .scenario_runner import ScenarioRunner, build_scenario_plan


class LocalSaasLabApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Local SaaS Simulation Lab")
        self.geometry("1460x920")
        self.minsize(1260, 780)

        self.store = LabConfigStore()
        self._load_state()

        self.status_var = tk.StringVar(value="Ready.")
        self.custom_route_var = tk.StringVar(value="#/staff/login")
        self.base_url_var = tk.StringVar(value=self.app_config.get("base_url", "http://127.0.0.1:9200"))
        self.chrome_path_var = tk.StringVar(value=self.app_config.get("chrome_path", ""))
        self.window_size_var = tk.StringVar(value=self.app_config.get("default_window_size", "1400,940"))
        self.launch_mode_var = tk.StringVar(value=self.app_config.get("default_launch_mode", "browser"))
        self.current_project_var = tk.StringVar(value=self.app_config.get("current_project", "ncs"))
        self.scenario_mode_var = tk.StringVar(value="assisted")
        self.reset_before_run_var = tk.BooleanVar(value=False)
        self.runner_launch_mode_var = tk.StringVar(value=self.app_config.get("default_launch_mode", "browser"))
        self.keep_windows_open_var = tk.BooleanVar(value=self.app_config.get("keep_windows_open_after_run", False))
        self.auto_open_artifact_var = tk.BooleanVar(value=self.app_config.get("artifacts_open_after_run", False))
        self.run_progress_var = tk.StringVar(value="Idle")
        self.run_status_detail_var = tk.StringVar(value="Ready to run a scenario.")
        self.run_current_step_var = tk.StringVar(value="No active step")
        self.run_current_actor_var = tk.StringVar(value="Current actor: -")
        self.run_current_url_var = tk.StringVar(value="Current URL: -")
        self.run_artifact_var = tk.StringVar(value="Artifact path: -")
        self.run_final_status_var = tk.StringVar(value="Final status: -")
        self.run_best_evidence_var = tk.StringVar(value="Best evidence: -")
        self.run_history_summary_var = tk.StringVar(value="No run selected")
        self._run_queue: queue.Queue = queue.Queue()
        self._run_thread: threading.Thread | None = None
        self._run_active = False
        self._latest_run_record = None
        self._runner_plan_index: dict[str, dict] = {}
        self._preserved_runtime_sessions: dict[str, dict] = {}
        self.runtime_engine = AutomationEngine()

        self._build_ui()
        self.refresh_all_views()

    def _load_state(self) -> None:
        self.app_config = self.store.load_app_config()
        if not self.app_config.get("chrome_path"):
            self.app_config["chrome_path"] = detect_chrome_path()
            self.store.save_app_config(self.app_config)

        self.projects = self.store.load_projects()
        self.presets = self.store.load_presets()
        self.profiles = self.store.load_profiles()
        self.scenarios = self.store.load_scenarios()
        self.selector_maps = self.store.load_selector_maps()
        self.run_history = self.store.load_run_history()
        self.active_sessions = self._reconcile_sessions(self.store.load_active_sessions())
        self.adapter = get_adapter(self.app_config.get("current_project", "ncs"))

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(self)
        notebook.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 0))

        self.profiles_tab = ttk.Frame(notebook)
        self.scenarios_tab = ttk.Frame(notebook)
        self.runner_tab = ttk.Frame(notebook)
        self.sessions_tab = ttk.Frame(notebook)
        self.artifacts_tab = ttk.Frame(notebook)
        self.adapter_tab = ttk.Frame(notebook)
        self.settings_tab = ttk.Frame(notebook)

        notebook.add(self.profiles_tab, text="Profiles")
        notebook.add(self.scenarios_tab, text="Scenarios")
        notebook.add(self.runner_tab, text="Scenario Runner")
        notebook.add(self.sessions_tab, text="Active Sessions")
        notebook.add(self.artifacts_tab, text="Artifacts / Run History")
        notebook.add(self.adapter_tab, text="Project Adapter")
        notebook.add(self.settings_tab, text="Settings")

        self._build_profiles_tab()
        self._build_scenarios_tab()
        self._build_runner_tab()
        self._build_sessions_tab()
        self._build_artifacts_tab()
        self._build_adapter_tab()
        self._build_settings_tab()

        status_bar = ttk.Label(self, textvariable=self.status_var, anchor="w")
        status_bar.grid(row=1, column=0, sticky="ew", padx=12, pady=(8, 12))

    def _build_profiles_tab(self) -> None:
        self.profiles_tab.columnconfigure(0, weight=3)
        self.profiles_tab.columnconfigure(1, weight=2)
        self.profiles_tab.rowconfigure(0, weight=1)

        left = ttk.Frame(self.profiles_tab, padding=10)
        right = ttk.Frame(self.profiles_tab, padding=10)
        left.grid(row=0, column=0, sticky="nsew")
        right.grid(row=0, column=1, sticky="nsew")
        left.rowconfigure(1, weight=1)
        right.rowconfigure(2, weight=1)

        ttk.Label(left, text="Lab Profiles").grid(row=0, column=0, sticky="w")
        columns = ("name", "kind", "role", "route", "mode")
        self.profiles_tree = ttk.Treeview(left, columns=columns, show="headings", height=20)
        for column, heading, width in [
            ("name", "Profile", 220),
            ("kind", "Kind", 90),
            ("role", "Role", 150),
            ("route", "Route", 240),
            ("mode", "Mode", 90),
        ]:
            self.profiles_tree.heading(column, text=heading)
            self.profiles_tree.column(column, width=width, anchor="w")
        self.profiles_tree.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.profiles_tree.bind("<<TreeviewSelect>>", lambda _event: self._render_profile_details())

        route_frame = ttk.LabelFrame(right, text="Launch")
        route_frame.grid(row=0, column=0, sticky="ew")
        ttk.Label(route_frame, text="Custom route or URL").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        ttk.Entry(route_frame, textvariable=self.custom_route_var).grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        route_frame.columnconfigure(0, weight=1)

        actions = ttk.LabelFrame(right, text="Profile Actions")
        actions.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        for index, spec in enumerate([
            ("Open", self.open_selected_profile),
            ("Open in App Mode", lambda: self.open_selected_profile("app")),
            ("Open Custom URL", self.open_selected_profile_custom),
            ("Create Profile", self.create_profile),
            ("Clone From Preset", self.clone_profile_from_preset),
            ("Edit Metadata", self.edit_profile),
            ("Copy Details", self.copy_profile_details),
            ("Close Session", self.close_selected_session),
            ("Reset Profile", self.reset_selected_profile),
            ("Delete Profile", self.delete_selected_profile),
        ]):
            ttk.Button(actions, text=spec[0], command=spec[1]).grid(row=index, column=0, sticky="ew", padx=8, pady=5)
        actions.columnconfigure(0, weight=1)

        self.profile_details = tk.Text(right, height=20, wrap="word")
        self.profile_details.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        self.profile_details.configure(state="disabled")

    def _build_scenarios_tab(self) -> None:
        self.scenarios_tab.columnconfigure(0, weight=3)
        self.scenarios_tab.columnconfigure(1, weight=2)
        self.scenarios_tab.rowconfigure(0, weight=1)

        left = ttk.Frame(self.scenarios_tab, padding=10)
        right = ttk.Frame(self.scenarios_tab, padding=10)
        left.grid(row=0, column=0, sticky="nsew")
        right.grid(row=0, column=1, sticky="nsew")
        left.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        columns = ("name", "actors", "modes")
        self.scenarios_tree = ttk.Treeview(left, columns=columns, show="headings", height=18)
        for column, heading, width in [
            ("name", "Scenario", 280),
            ("actors", "Actors", 80),
            ("modes", "Modes", 180),
        ]:
            self.scenarios_tree.heading(column, text=heading)
            self.scenarios_tree.column(column, width=width, anchor="w")
        self.scenarios_tree.grid(row=0, column=0, sticky="nsew")
        self.scenarios_tree.bind("<<TreeviewSelect>>", lambda _event: self._sync_selected_scenario())

        ttk.Button(right, text="Send to Runner", command=self._sync_selected_scenario).grid(row=0, column=0, sticky="ew")
        self.scenario_details = tk.Text(right, wrap="word")
        self.scenario_details.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.scenario_details.configure(state="disabled")

    def _build_runner_tab(self) -> None:
        self.runner_tab.columnconfigure(0, weight=2)
        self.runner_tab.columnconfigure(1, weight=3)
        self.runner_tab.rowconfigure(0, weight=1)

        left = ttk.Frame(self.runner_tab, padding=10)
        right = ttk.Frame(self.runner_tab, padding=10)
        left.grid(row=0, column=0, sticky="nsew")
        right.grid(row=0, column=1, sticky="nsew")
        left.rowconfigure(2, weight=1)
        right.rowconfigure(1, weight=1)

        ttk.Label(left, text="Selected Scenario").grid(row=0, column=0, sticky="w")
        self.runner_scenario_var = tk.StringVar(value="No scenario selected")
        ttk.Label(left, textvariable=self.runner_scenario_var, font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky="w", pady=(4, 10))

        controls = ttk.LabelFrame(left, text="Run Controls")
        controls.grid(row=2, column=0, sticky="nsew")
        ttk.Label(controls, text="Mode").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        ttk.Combobox(controls, textvariable=self.scenario_mode_var, values=["manual", "assisted", "automated"], state="readonly").grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        ttk.Label(controls, text="Presentation").grid(row=2, column=0, sticky="w", padx=8, pady=(0, 2))
        ttk.Combobox(controls, textvariable=self.runner_launch_mode_var, values=["browser", "app"], state="readonly").grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 8))
        ttk.Checkbutton(controls, text="Reset actor profiles before run", variable=self.reset_before_run_var).grid(row=4, column=0, sticky="w", padx=8, pady=(0, 4))
        ttk.Checkbutton(controls, text="Keep browser windows open after run", variable=self.keep_windows_open_var).grid(row=5, column=0, sticky="w", padx=8, pady=(0, 4))
        ttk.Checkbutton(controls, text="Auto-open artifact folder on completion", variable=self.auto_open_artifact_var).grid(row=6, column=0, sticky="w", padx=8, pady=(0, 8))
        self.run_scenario_button = ttk.Button(controls, text="Run Scenario", command=self.run_selected_scenario)
        self.run_scenario_button.grid(row=7, column=0, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(controls, text="Refresh Plan", command=self._render_runner_plan).grid(row=8, column=0, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(controls, text="Open Latest Artifact", command=self.open_latest_artifact_for_selected_scenario).grid(row=9, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.automation_backend_var = tk.StringVar(value="")
        self.automation_reason_var = tk.StringVar(value="")
        ttk.Label(controls, textvariable=self.automation_backend_var).grid(row=10, column=0, sticky="w", padx=8, pady=(0, 2))
        ttk.Label(controls, textvariable=self.automation_reason_var, wraplength=320, justify="left").grid(row=11, column=0, sticky="w", padx=8, pady=(0, 8))
        controls.columnconfigure(0, weight=1)

        self.runner_notes = tk.Text(left, height=16, wrap="word")
        self.runner_notes.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        self.runner_notes.configure(state="disabled")

        live_summary = ttk.LabelFrame(right, text="Live Run Summary")
        live_summary.grid(row=0, column=0, sticky="ew")
        live_summary.columnconfigure(1, weight=1)
        ttk.Label(live_summary, text="Progress").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        ttk.Label(live_summary, textvariable=self.run_progress_var).grid(row=0, column=1, sticky="w", padx=8, pady=(8, 2))
        ttk.Label(live_summary, text="Current step").grid(row=1, column=0, sticky="w", padx=8, pady=(0, 2))
        ttk.Label(live_summary, textvariable=self.run_current_step_var, wraplength=520, justify="left").grid(row=1, column=1, sticky="w", padx=8, pady=(0, 2))
        ttk.Label(live_summary, text="Scenario status").grid(row=2, column=0, sticky="w", padx=8, pady=(0, 2))
        ttk.Label(live_summary, textvariable=self.run_status_detail_var, wraplength=520, justify="left").grid(row=2, column=1, sticky="w", padx=8, pady=(0, 2))
        ttk.Label(live_summary, text="Current actor").grid(row=3, column=0, sticky="w", padx=8, pady=(0, 2))
        ttk.Label(live_summary, textvariable=self.run_current_actor_var, wraplength=520, justify="left").grid(row=3, column=1, sticky="w", padx=8, pady=(0, 2))
        ttk.Label(live_summary, text="Current URL").grid(row=4, column=0, sticky="w", padx=8, pady=(0, 2))
        ttk.Label(live_summary, textvariable=self.run_current_url_var, wraplength=520, justify="left").grid(row=4, column=1, sticky="w", padx=8, pady=(0, 2))
        ttk.Label(live_summary, text="Final result").grid(row=5, column=0, sticky="w", padx=8, pady=(0, 2))
        ttk.Label(live_summary, textvariable=self.run_final_status_var, wraplength=520, justify="left").grid(row=5, column=1, sticky="w", padx=8, pady=(0, 2))
        ttk.Label(live_summary, text="Best evidence").grid(row=6, column=0, sticky="w", padx=8, pady=(0, 2))
        ttk.Label(live_summary, textvariable=self.run_best_evidence_var, wraplength=520, justify="left").grid(row=6, column=1, sticky="w", padx=8, pady=(0, 2))
        ttk.Label(live_summary, text="Artifact").grid(row=7, column=0, sticky="w", padx=8, pady=(0, 8))
        ttk.Label(live_summary, textvariable=self.run_artifact_var, wraplength=520, justify="left").grid(row=7, column=1, sticky="w", padx=8, pady=(0, 8))

        columns = ("step", "actor", "mode", "action", "status")
        self.runner_plan_tree = ttk.Treeview(right, columns=columns, show="headings", height=22)
        for column, heading, width in [
            ("step", "Step", 280),
            ("actor", "Actor", 150),
            ("mode", "Mode", 100),
            ("action", "Action", 140),
            ("status", "Status", 120),
        ]:
            self.runner_plan_tree.heading(column, text=heading)
            self.runner_plan_tree.column(column, width=width, anchor="w")
        self.runner_plan_tree.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

        bottom = ttk.Panedwindow(right, orient="horizontal")
        bottom.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        right.rowconfigure(2, weight=1)

        step_frame = ttk.LabelFrame(bottom, text="Step / Result Details")
        log_frame = ttk.LabelFrame(bottom, text="Live Output")
        bottom.add(step_frame, weight=1)
        bottom.add(log_frame, weight=1)
        step_frame.rowconfigure(0, weight=1)
        step_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.runner_step_details = tk.Text(step_frame, wrap="word")
        self.runner_step_details.grid(row=0, column=0, sticky="nsew")
        self.runner_step_details.configure(state="disabled")
        self.runner_log_text = tk.Text(log_frame, wrap="word")
        self.runner_log_text.grid(row=0, column=0, sticky="nsew")
        self.runner_log_text.configure(state="disabled")
        self.runner_plan_tree.bind("<<TreeviewSelect>>", lambda _event: self._render_runner_step_details())

    def _build_sessions_tab(self) -> None:
        self.sessions_tab.columnconfigure(0, weight=1)
        self.sessions_tab.rowconfigure(1, weight=1)

        top = ttk.Frame(self.sessions_tab, padding=10)
        top.grid(row=0, column=0, sticky="ew")
        ttk.Button(top, text="Refresh", command=self.refresh_active_sessions).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(top, text="Close Selected", command=self.close_selected_session).grid(row=0, column=1)

        columns = ("profile", "state", "mode", "url", "launched")
        self.sessions_tree = ttk.Treeview(self.sessions_tab, columns=columns, show="headings", height=18)
        for column, heading, width in [
            ("profile", "Profile", 220),
            ("state", "State", 170),
            ("mode", "Mode", 110),
            ("url", "URL", 420),
            ("launched", "Launched At", 170),
        ]:
            self.sessions_tree.heading(column, text=heading)
            self.sessions_tree.column(column, width=width, anchor="w")
        self.sessions_tree.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

    def _build_artifacts_tab(self) -> None:
        self.artifacts_tab.columnconfigure(0, weight=3)
        self.artifacts_tab.columnconfigure(1, weight=2)
        self.artifacts_tab.rowconfigure(0, weight=1)

        left = ttk.Frame(self.artifacts_tab, padding=10)
        right = ttk.Frame(self.artifacts_tab, padding=10)
        left.grid(row=0, column=0, sticky="nsew")
        right.grid(row=0, column=1, sticky="nsew")
        left.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        columns = ("scenario", "mode", "status", "started")
        self.artifacts_tree = ttk.Treeview(left, columns=columns, show="headings", height=20)
        for column, heading, width in [
            ("scenario", "Scenario", 260),
            ("mode", "Mode", 100),
            ("status", "Status", 140),
            ("started", "Started", 170),
        ]:
            self.artifacts_tree.heading(column, text=heading)
            self.artifacts_tree.column(column, width=width, anchor="w")
        self.artifacts_tree.grid(row=0, column=0, sticky="nsew")
        self.artifacts_tree.bind("<<TreeviewSelect>>", lambda _event: self._render_run_details())

        actions = ttk.LabelFrame(right, text="Run History Actions")
        actions.grid(row=0, column=0, sticky="ew")
        ttk.Button(actions, text="Open Artifact Folder", command=self.open_selected_artifact_folder).grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 6))
        ttk.Button(actions, text="Open Summary", command=self.open_selected_summary).grid(row=1, column=0, sticky="ew", padx=8, pady=6)
        ttk.Button(actions, text="Open Best Evidence", command=self.open_selected_best_evidence).grid(row=2, column=0, sticky="ew", padx=8, pady=6)
        ttk.Button(actions, text="Open Latest Artifact", command=self.open_latest_artifact_for_selected_scenario).grid(row=3, column=0, sticky="ew", padx=8, pady=6)
        ttk.Button(actions, text="Clear Selected History", command=self.clear_selected_run_history).grid(row=4, column=0, sticky="ew", padx=8, pady=6)
        ttk.Button(actions, text="Clear All History", command=self.clear_all_run_history).grid(row=5, column=0, sticky="ew", padx=8, pady=(6, 8))
        actions.columnconfigure(0, weight=1)

        ttk.Label(right, textvariable=self.run_history_summary_var, justify="left", wraplength=360).grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.run_details = tk.Text(right, wrap="word")
        self.run_details.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        self.run_details.configure(state="disabled")

    def _build_adapter_tab(self) -> None:
        self.adapter_tab.columnconfigure(0, weight=1)
        self.adapter_tab.rowconfigure(1, weight=1)

        header = ttk.Frame(self.adapter_tab, padding=10)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Current Project").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.current_project_var, font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.adapter_text = tk.Text(self.adapter_tab, wrap="word")
        self.adapter_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.adapter_text.configure(state="disabled")

    def _build_settings_tab(self) -> None:
        frame = ttk.Frame(self.settings_tab, padding=14)
        frame.grid(row=0, column=0, sticky="nsew")
        self.settings_tab.columnconfigure(0, weight=1)

        ttk.Label(frame, text="Frontend base URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.base_url_var, width=60).grid(row=1, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(frame, text="Chrome executable path").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.chrome_path_var, width=60).grid(row=3, column=0, sticky="ew", pady=(0, 6))

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, sticky="w", pady=(0, 10))
        ttk.Button(buttons, text="Detect Chrome", command=self.detect_chrome).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Browse", command=self.browse_chrome).grid(row=0, column=1)

        ttk.Label(frame, text="Current project adapter").grid(row=5, column=0, sticky="w")
        ttk.Combobox(
            frame,
            textvariable=self.current_project_var,
            values=[adapter.project_id for adapter in list_adapters()],
            state="readonly",
        ).grid(row=6, column=0, sticky="w", pady=(0, 10))
        ttk.Label(frame, text="Default launch mode").grid(row=7, column=0, sticky="w")
        ttk.Combobox(frame, textvariable=self.launch_mode_var, values=["browser", "app"], state="readonly").grid(row=8, column=0, sticky="w", pady=(0, 10))
        ttk.Label(frame, text="Default window size").grid(row=9, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.window_size_var, width=18).grid(row=10, column=0, sticky="w", pady=(0, 12))
        ttk.Checkbutton(frame, text="Keep windows open after automated runs", variable=self.keep_windows_open_var).grid(row=11, column=0, sticky="w", pady=(0, 6))
        ttk.Checkbutton(frame, text="Auto-open artifact folder after run", variable=self.auto_open_artifact_var).grid(row=12, column=0, sticky="w", pady=(0, 12))
        ttk.Button(frame, text="Save Settings", command=self.save_settings).grid(row=13, column=0, sticky="w")

    def refresh_all_views(self) -> None:
        self._load_profiles_tree()
        self._load_scenarios_tree()
        self._load_sessions_tree()
        self._load_artifacts_tree()
        self._refresh_automation_status()
        self._render_adapter_reference()
        self._render_profile_details()
        self._render_scenario_details()
        self._render_runner_plan()
        self._render_run_details()

    def _filtered_profiles(self) -> list[dict]:
        return [profile for profile in self.profiles if profile.get("project_id", "ncs") == self.current_project_var.get()]

    def _filtered_scenarios(self) -> list[dict]:
        return [scenario for scenario in self.scenarios if scenario.get("project_id", "ncs") == self.current_project_var.get()]

    def _filtered_runs(self) -> list[dict]:
        return [run for run in self.run_history if run.get("project_id", "ncs") == self.current_project_var.get()]

    def _reconcile_sessions(self, sessions):
        live_sessions = []
        for session in sessions:
            pid = int(session.get("pid", 0))
            if pid and pid_is_running(pid):
                live_sessions.append(session)
        self.store.save_active_sessions(live_sessions)
        return live_sessions

    def _combined_sessions(self) -> list[dict]:
        sessions = list(self.active_sessions)
        sessions.extend(
            sorted(
                (session["display"] for session in self._preserved_runtime_sessions.values()),
                key=lambda item: (item.get("launched_at", ""), item.get("profile_name", "")),
            )
        )
        return sessions

    def _has_any_session_for_profile(self, profile_id: str) -> bool:
        return any(session["profile_id"] == profile_id for session in self._combined_sessions())

    def _load_profiles_tree(self) -> None:
        self.profiles_tree.delete(*self.profiles_tree.get_children())
        for profile in self._filtered_profiles():
            self.profiles_tree.insert("", "end", iid=profile["id"], values=(profile["name"], profile["kind"], profile["role"], profile["route"], profile["launch_mode"]))

    def _load_scenarios_tree(self) -> None:
        self.scenarios_tree.delete(*self.scenarios_tree.get_children())
        for scenario in self._filtered_scenarios():
            self.scenarios_tree.insert(
                "",
                "end",
                iid=scenario["id"],
                values=(scenario["name"], len(scenario.get("participants", [])), ", ".join(scenario.get("supported_modes", []))),
            )

    def _load_sessions_tree(self) -> None:
        self.sessions_tree.delete(*self.sessions_tree.get_children())
        for session in self._combined_sessions():
            state_display = session.get("state_display")
            if not state_display:
                pid = session.get("pid")
                state_display = f"PID {pid}" if pid else session.get("inspection_label", "-")
            self.sessions_tree.insert(
                "",
                "end",
                iid=session["id"],
                values=(session["profile_name"], state_display, session["launch_mode"], session["url"], session["launched_at"]),
            )

    def _load_artifacts_tree(self) -> None:
        self.artifacts_tree.delete(*self.artifacts_tree.get_children())
        for run in self._filtered_runs():
            self.artifacts_tree.insert("", "end", iid=run["id"], values=(run["scenario_name"], run["mode"], run["status"], run["started_at"]))

    def _render_profile_details(self) -> None:
        profile = self.get_selected_profile()
        payload = ""
        if profile:
            metadata = legacy_metadata_for_display(profile)
            lines = [
                f"Name: {profile['name']}",
                f"ID: {profile['id']}",
                f"Project: {profile.get('project_id', 'ncs')}",
                f"Preset: {profile.get('preset_id', '-')}",
                f"Role: {profile['role']}",
                f"Kind: {profile['kind']}",
                f"Base route: {profile.get('base_route', profile['route'])}",
                f"Landing route: {profile.get('landing_route', profile['route'])}",
                f"Launch mode: {profile['launch_mode']}",
                f"Locale/theme: {profile.get('locale', 'en-US')} / {profile.get('theme', 'system')}",
                f"Tags: {', '.join(profile.get('tags', [])) or '-'}",
                f"Chrome data dir: {profile_data_dir(CHROME_DATA_DIR, profile['id'])}",
                f"Notes: {profile.get('notes', '-')}",
                "",
                "Actionable metadata:",
            ]
            lines.extend(f"- {key}: {value}" for key, value in metadata.items() if value)
            payload = "\n".join(lines)
        self._set_text(self.profile_details, payload)

    def _render_scenario_details(self) -> None:
        scenario = self.get_selected_scenario()
        payload = ""
        if scenario:
            lines = [
                scenario["name"],
                "",
                scenario.get("summary", ""),
                scenario.get("description", ""),
                "",
                f"Goal: {scenario.get('goal', '-')}",
                f"Supported modes: {', '.join(scenario.get('supported_modes', []))}",
                "",
                "Participants:",
            ]
            for participant in scenario.get("participants", []):
                lines.append(f"- {participant['id']}: {participant['preset_id']} -> {participant.get('route', 'preset route')}")
            lines.extend(["", "Flow steps:"])
            for step in scenario.get("steps", []):
                lines.append(f"- [{step.get('mode', 'manual')}] {step['title']} ({step.get('action', '-')})")
            payload = "\n".join(lines)
        self._set_text(self.scenario_details, payload)

    def _render_runner_plan(self) -> None:
        self.runner_plan_tree.delete(*self.runner_plan_tree.get_children())
        self._runner_plan_index = {}
        scenario = self.get_selected_scenario()
        if not scenario:
            self.runner_scenario_var.set("No scenario selected")
            self._set_text(self.runner_notes, "")
            self._set_text(self.runner_step_details, "")
            return

        self.runner_scenario_var.set(scenario["name"])
        plan = build_scenario_plan(scenario, self._filtered_profiles(), self.scenario_mode_var.get())
        notes = [
            scenario.get("summary", ""),
            "",
            f"Mode: {self.scenario_mode_var.get()}",
            f"Presentation: {self.runner_launch_mode_var.get()}",
            f"Goal: {scenario.get('goal', '-')}",
            f"Keep windows open: {'yes' if self.keep_windows_open_var.get() else 'no'}",
            f"Auto-open artifacts: {'yes' if self.auto_open_artifact_var.get() else 'no'}",
        ]
        for item in plan:
            self.runner_plan_tree.insert("", "end", iid=item["id"], values=(item["title"], item["actor_name"], item["mode"], item["action"], item["planned_status"]))
            self._runner_plan_index[item["id"]] = item
        self._set_text(self.runner_notes, "\n".join(notes))
        self._set_text(self.runner_step_details, "")

    def _render_runner_step_details(self) -> None:
        selected = self.runner_plan_tree.selection()
        if not selected:
            self._set_text(self.runner_step_details, "")
            return
        step_id = selected[0]
        step = self._runner_plan_index.get(step_id)
        if not step:
            self._set_text(self.runner_step_details, "")
            return
        lines = [
            f"Step: {step['title']}",
            f"Actor: {step['actor_name']}",
            f"Mode: {step['mode']}",
            f"Action: {step['action']}",
            f"Status: {step.get('live_status', step.get('planned_status', '-'))}",
            f"Resolution: {step.get('live_resolution', step.get('resolution', '-'))}",
            f"Assertion: {step['assertion'] or '-'}",
            f"Guidance: {step['guidance'] or '-'}",
        ]
        if step.get("live_message"):
            lines.append(f"Message: {step['live_message']}")
        if step.get("current_url"):
            lines.append(f"Current URL: {step['current_url']}")
        if step.get("reason"):
            lines.append(f"Reason: {step['reason']}")
        if step.get("screenshot"):
            lines.append(f"Screenshot: {step['screenshot']}")
        self._set_text(self.runner_step_details, "\n".join(lines))

    def _render_run_details(self) -> None:
        selection = self.artifacts_tree.selection()
        if not selection:
            self._set_text(self.run_details, "")
            self.run_history_summary_var.set("No run selected")
            return
        run = next((item for item in self.run_history if item["id"] == selection[0]), None)
        if not run:
            self._set_text(self.run_details, "")
            self.run_history_summary_var.set("No run selected")
            return
        screenshot_count = len([step for step in run.get("steps", []) if step.get("screenshot")])
        best_evidence_count = len(run.get("best_evidence", []))
        self.run_history_summary_var.set(
            f"{run['scenario_name']} | {run['status']} | {run.get('mode', '-')} | screenshots: {screenshot_count} | best evidence: {best_evidence_count}"
        )
        lines = [
            run["scenario_name"],
            "",
            f"Status: {run['status']}",
            f"Mode: {run['mode']}",
            f"Presentation: {run.get('launch_mode', '-')}",
            f"Started: {run['started_at']}",
            f"Ended: {run.get('ended_at', '-')}",
            f"Artifact dir: {run.get('artifact_dir', '-')}",
            f"Summary: {run.get('summary', '-')}",
            f"Keep-open requested: {run.get('inspection_overview', {}).get('keep_windows_open_requested', False)}",
            f"True live preservation: {run.get('inspection_overview', {}).get('true_keep_open', False)}",
            f"Fallback reopen used: {run.get('inspection_overview', {}).get('fallback_reopen_used', False)}",
            "",
            "Actor sessions:",
        ]
        for session in run.get("actor_sessions", []):
            lines.append(
                f"- {session['actor_name']} :: steps={len(session.get('steps', []))} :: reused={session.get('reused', False)} :: kept_open={session.get('kept_open', False)}"
            )
            if session.get("inspection_label"):
                lines.append(f"  Inspection: {session['inspection_label']}")
            if session.get("auth_label"):
                lines.append(f"  Auth: {session['auth_label']}")
            if session.get("final_url"):
                lines.append(f"  Final URL: {session['final_url']}")
            if session.get("final_screenshot"):
                lines.append(f"  Final screenshot: {session['final_screenshot']}")
            if session.get("fallback_reason"):
                lines.append(f"  Fallback reason: {session['fallback_reason']}")
        lines.extend([
            "",
            "Best evidence:",
        ])
        for evidence in run.get("best_evidence", []):
            lines.append(f"- {evidence.get('label', '-')} [{evidence.get('type', '-')}] :: {evidence.get('path', '-')}")
        lines.extend([
            "",
            "Step results:",
        ])
        for step in run.get("steps", []):
            lines.append(f"- [{step['status']}] {step['actor']} :: {step['title']} ({step.get('action', '-')}) :: {step['message']}")
            if step.get("resolution"):
                lines.append(f"  Resolution: {step['resolution']}")
            if step.get("current_url"):
                lines.append(f"  URL: {step['current_url']}")
            if step.get("reason"):
                lines.append(f"  Reason: {step['reason']}")
            if step.get("evidence_type"):
                lines.append(f"  Evidence: {step['evidence_type']}")
            if step.get("screenshot"):
                lines.append(f"  Screenshot: {step['screenshot']}")
        self._set_text(self.run_details, "\n".join(lines))

    def _refresh_automation_status(self) -> None:
        engine = ScenarioRunner(
            self.store,
            self.app_config,
            self.selector_maps.get(self.current_project_var.get(), {}),
        ).engine
        self.automation_backend_var.set(f"Automation backend: {engine.backend_name}")
        self.automation_reason_var.set(engine.describe())

    def _render_adapter_reference(self) -> None:
        adapter = get_adapter(self.current_project_var.get())
        lines = [
            f"Project: {adapter.name}",
            f"Adapter ID: {adapter.project_id}",
            "",
            adapter.description,
            "",
            "Seeder / project reference:",
        ]
        lines.extend(f"- {line}" for line in adapter.get_seed_reference_lines())
        lines.extend([
            "",
            "Adapter capabilities:",
            "- Generic preset metadata with project-specific login/token handling",
            "- Scenario definitions with explicit participants and ordered steps",
            "- Optional Playwright automation with honest fallback to assisted/manual flows",
            "- Artifact and run-history generation under runtime/artifacts and runtime/state",
        ])
        self._set_text(self.adapter_text, "\n".join(lines))

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def get_selected_profile(self):
        selection = self.profiles_tree.selection()
        if not selection:
            return None
        selected_id = selection[0]
        return next((profile for profile in self.profiles if profile["id"] == selected_id), None)

    def get_selected_scenario(self):
        selection = self.scenarios_tree.selection()
        if not selection:
            return None
        selected_id = selection[0]
        return next((scenario for scenario in self.scenarios if scenario["id"] == selected_id), None)

    def _sync_selected_scenario(self) -> None:
        scenario = self.get_selected_scenario()
        if not scenario:
            messagebox.showinfo("Local SaaS Lab", "Select a scenario first.")
            return
        self.runner_scenario_var.set(scenario["name"])
        self.scenario_mode_var.set(scenario.get("default_mode", "assisted"))
        self._render_scenario_details()
        self._render_runner_plan()

    def open_selected_profile(self, launch_mode=None) -> None:
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("Local SaaS Lab", "Select a profile first.")
            return
        self._launch_profile(profile, profile["route"], launch_mode or profile["launch_mode"])

    def open_selected_profile_custom(self) -> None:
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("Local SaaS Lab", "Select a profile first.")
            return
        self._launch_profile(profile, self.custom_route_var.get().strip() or profile["route"], profile["launch_mode"])

    def _launch_profile(self, profile, route: str, launch_mode: str) -> None:
        chrome_path = self.chrome_path_var.get().strip()
        if not chrome_path or not Path(chrome_path).exists():
            messagebox.showerror("Local SaaS Lab", "Set a valid Chrome executable path first.")
            return

        url = resolve_url(self.base_url_var.get().strip(), route)
        profile_dir = profile_data_dir(CHROME_DATA_DIR, profile["id"])
        command = build_launch_command(
            chrome_path=chrome_path,
            profile_dir=profile_dir,
            url=url,
            launch_mode=launch_mode,
            window_size=self.window_size_var.get().strip(),
            new_window=True,
        )
        profile_dir.mkdir(parents=True, exist_ok=True)
        process = launch_chrome(command)
        session_id = f"{profile['id']}-{process.pid}"
        self.active_sessions = [session for session in self.active_sessions if session["id"] != session_id]
        self.active_sessions.append(
            {
                "id": session_id,
                "profile_id": profile["id"],
                "profile_name": profile["name"],
                "pid": process.pid,
                "url": url,
                "launch_mode": launch_mode,
                "launched_at": "manual-launch",
            }
        )
        self.store.save_active_sessions(self.active_sessions)
        self._load_sessions_tree()
        self.status_var.set(f"Launched {profile['name']} at {url}")

    def run_selected_scenario(self) -> None:
        if self._run_active:
            messagebox.showinfo("Local SaaS Lab", "A scenario run is already in progress.")
            return
        scenario = self.get_selected_scenario()
        if not scenario:
            messagebox.showinfo("Local SaaS Lab", "Select a scenario first.")
            return
        chrome_path = self.chrome_path_var.get().strip()
        if not chrome_path or not Path(chrome_path).exists():
            messagebox.showerror("Local SaaS Lab", "Set a valid Chrome executable path first.")
            return
        try:
            if self.reset_before_run_var.get():
                self._reset_profiles_for_scenario(scenario)
        except Exception as exc:  # noqa: BLE001 - keep the operator console resilient
            messagebox.showerror("Local SaaS Lab", str(exc))
            self.status_var.set(f"Scenario run failed before execution: {exc}")
            return

        self._run_active = True
        self.run_scenario_button.configure(state="disabled")
        self.run_progress_var.set("Starting run...")
        self.run_status_detail_var.set("Preparing scenario execution.")
        self.run_current_step_var.set("Waiting for first step...")
        self.run_current_actor_var.set("Current actor: -")
        self.run_current_url_var.set("Current URL: -")
        self.run_final_status_var.set("Final status: running")
        self.run_artifact_var.set("Artifact path: pending")
        self.run_best_evidence_var.set("Best evidence: pending")
        self._set_text(self.runner_log_text, "")
        self._latest_run_record = None
        self._render_runner_plan()

        run_options = {
            "scenario": scenario,
            "profiles": self._filtered_profiles(),
            "mode": self.scenario_mode_var.get(),
            "chrome_data_root": CHROME_DATA_DIR,
            "chrome_path": chrome_path,
            "launch_mode_override": self.runner_launch_mode_var.get(),
            "keep_windows_open": self.keep_windows_open_var.get(),
            "live_preservation_supported": True,
            "reusable_runtime_sessions": self._detach_reusable_runtime_sessions_for_scenario(scenario),
        }
        self._run_thread = threading.Thread(target=self._run_scenario_worker, args=(run_options,), daemon=True)
        self._run_thread.start()
        self.after(120, self._poll_run_events)

    def _run_scenario_worker(self, run_options: dict) -> None:
        runner = ScenarioRunner(
            self.store,
            {
                **self.app_config,
                "base_url": self.base_url_var.get().strip(),
                "default_window_size": self.window_size_var.get().strip(),
            },
            self.selector_maps.get(self.current_project_var.get(), {}),
        )
        try:
            runner.run(
                event_callback=self._queue_run_event,
                **run_options,
            )
        except Exception as exc:  # noqa: BLE001 - keep the operator console resilient
            self._queue_run_event({"type": "scenario_crashed", "message": str(exc)})

    def _queue_run_event(self, event: dict) -> None:
        self._run_queue.put(event)

    def _poll_run_events(self) -> None:
        while True:
            try:
                event = self._run_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_run_event(event)

        if self._run_active or not self._run_queue.empty():
            self.after(120, self._poll_run_events)

    def _handle_run_event(self, event: dict) -> None:
        event_type = event.get("type")
        if event_type == "scenario_started":
            self.run_progress_var.set(f"0 / {event.get('total_steps', 0)} steps")
            self.run_status_detail_var.set(
                f"Running {event.get('scenario_name', 'scenario')} in {event.get('mode', '-')} mode using {event.get('launch_mode', 'browser')} presentation."
            )
            self._append_runner_log(
                f"[run] started {event.get('scenario_name', 'scenario')} | mode={event.get('mode', '-')} | launch={event.get('launch_mode', 'browser')}"
            )
            return

        if event_type == "log":
            self._append_runner_log(event.get("message", ""))
            return

        if event_type == "step_update":
            self._apply_live_step_update(event)
            return

        if event_type == "scenario_finished":
            self._finalize_run_ui(
                event.get("run_record"),
                event.get("preserved_runtime_sessions", []),
            )
            return

        if event_type == "scenario_crashed":
            self._run_active = False
            self.run_scenario_button.configure(state="normal")
            self.run_final_status_var.set("Final status: failed")
            self.run_status_detail_var.set(event.get("message", "Scenario run crashed before finishing."))
            self._append_runner_log(f"[error] {event.get('message', 'Scenario crashed')}")
            self.status_var.set(f"Scenario run crashed: {event.get('message', 'unknown error')}")

    def _apply_live_step_update(self, event: dict) -> None:
        step_id = event.get("step_id", "")
        item = self._runner_plan_index.get(step_id)
        if item:
            item["live_status"] = event.get("status", "")
            item["live_message"] = event.get("message", "")
            item["current_url"] = event.get("current_url", "")
            item["reason"] = event.get("reason", "")
            item["live_resolution"] = event.get("resolution", "")
            if event.get("screenshot"):
                item["screenshot"] = event["screenshot"]
            if self.runner_plan_tree.exists(step_id):
                current_values = list(self.runner_plan_tree.item(step_id, "values"))
                if current_values:
                    current_values[-1] = event.get("status", "")
                    self.runner_plan_tree.item(step_id, values=current_values)
        self.run_progress_var.set(f"{event.get('index', 0)} / {event.get('total_steps', 0)} steps")
        self.run_current_step_var.set(f"{event.get('title', '-') } ({event.get('status', '-')})")
        self.run_current_actor_var.set(f"Current actor: {event.get('actor', '-')}")
        self.run_current_url_var.set(f"Current URL: {event.get('current_url', '-') or '-'}")
        self.run_status_detail_var.set(event.get("message", ""))
        self._append_runner_log(self._format_step_event_line(event))
        self._render_runner_step_details()

    def _finalize_run_ui(
        self,
        run_record: dict | None,
        preserved_runtime_sessions: list[dict] | None = None,
    ) -> None:
        self._run_active = False
        self.run_scenario_button.configure(state="normal")
        if not run_record:
            self.run_final_status_var.set("Final status: failed")
            self.run_status_detail_var.set("Scenario finished without a valid run record.")
            return

        self._store_preserved_runtime_sessions(run_record, preserved_runtime_sessions or [])
        self._latest_run_record = run_record
        self.run_history = self.store.load_run_history()
        self.active_sessions = self._reconcile_sessions(self.store.load_active_sessions())
        self._load_sessions_tree()
        self._load_artifacts_tree()
        if self.artifacts_tree.exists(run_record["id"]):
            self.artifacts_tree.selection_set(run_record["id"])
            self.artifacts_tree.focus(run_record["id"])
        self._render_run_details()
        self.run_final_status_var.set(f"Final status: {run_record.get('status', '-')}")
        self.run_status_detail_var.set(run_record.get("summary", "Scenario finished."))
        self.run_artifact_var.set(f"Artifact path: {run_record.get('artifact_dir', '-')}")
        self.run_best_evidence_var.set(f"Best evidence: {self._best_evidence_label(run_record)}")
        self.status_var.set(run_record.get("summary", "Scenario finished."))
        self._append_runner_log(f"[run] finished with status={run_record.get('status', '-')}")
        recovery = run_record.get("recovery_overview", {})
        if recovery.get("recovery_occurred"):
            self._append_runner_log(
                f"[run] recovery noted | recovered={recovery.get('recovered_failure_count', 0)} | unrecovered={recovery.get('unrecovered_failure_count', 0)}"
            )
        if self.auto_open_artifact_var.get() and run_record.get("artifact_dir"):
            self._open_path(run_record["artifact_dir"])

    def _store_preserved_runtime_sessions(
        self,
        run_record: dict,
        preserved_runtime_sessions: list[dict],
    ) -> None:
        if not preserved_runtime_sessions:
            return
        actor_summary_by_participant = {
            actor.get("participant_id"): actor for actor in run_record.get("actor_sessions", []) if actor.get("participant_id")
        }
        for session in preserved_runtime_sessions:
            participant_id = session.get("participant_id", "")
            actor_summary = actor_summary_by_participant.get(participant_id, {})
            session_id = f"live::{run_record['id']}::{participant_id}"
            self._preserved_runtime_sessions[session_id] = {
                "runtime": session,
                "runtime_handle": session.get("runtime_handle"),
                "runtime_bundle_id": session.get("runtime_bundle_id", f"runtime::{run_record['id']}"),
                "run_id": run_record["id"],
                "display": {
                    "id": session_id,
                    "profile_id": session.get("preset_id", ""),
                    "profile_name": session.get("actor_name", participant_id or "actor"),
                    "pid": "",
                    "url": actor_summary.get("final_url", getattr(session.get("page"), "url", "")),
                    "launch_mode": session.get("launch_mode", run_record.get("launch_mode", "browser")),
                    "launched_at": run_record.get("ended_at") or run_record.get("started_at", ""),
                    "state_display": (
                        f"{actor_summary.get('inspection_label', 'Live preserved session')} | "
                        f"{actor_summary.get('auth_label', 'Live authenticated page preserved')}"
                    ),
                    "inspection_label": actor_summary.get("inspection_label", "Live preserved session"),
                    "auth_label": actor_summary.get("auth_label", "Live authenticated page preserved"),
                    "session_origin": "live-preserved",
                    "run_id": run_record["id"],
                },
            }
            self._append_runner_log(
                f"[keep-open] preserved live session for {session.get('actor_name', participant_id or 'actor')} | "
                f"{actor_summary.get('inspection_label', 'Live preserved session')} | "
                f"{actor_summary.get('auth_label', 'Live authenticated page preserved')}"
            )

    def _reset_profiles_for_scenario(self, scenario: dict) -> None:
        participant_profile_ids = {participant["preset_id"] for participant in scenario.get("participants", [])}
        if any(session["profile_id"] in participant_profile_ids for session in self._combined_sessions()):
            raise RuntimeError("Close active sessions for the scenario profiles before running with reset enabled.")
        for profile_id in participant_profile_ids:
            delete_profile_dir(profile_data_dir(CHROME_DATA_DIR, profile_id), CHROME_DATA_DIR)

    def _detach_reusable_runtime_sessions_for_scenario(self, scenario: dict) -> list[dict]:
        reusable: list[dict] = []
        participant_profile_ids = {participant["preset_id"] for participant in scenario.get("participants", [])}
        removable_ids = [session_id for session_id, item in self._preserved_runtime_sessions.items() if item["display"]["profile_id"] in participant_profile_ids]
        for session_id in removable_ids:
            preserved = self._preserved_runtime_sessions.pop(session_id, None)
            if not preserved:
                continue
            reusable.append(
                {
                    "runtime": preserved["runtime"],
                    "runtime_handle": preserved.get("runtime_handle"),
                    "runtime_bundle_id": preserved.get("runtime_bundle_id", ""),
                }
            )
            self._append_runner_log(
                f"[keep-open] reusing preserved live session for {preserved['display'].get('profile_name', preserved['display'].get('profile_id', 'profile'))}"
            )
        return reusable

    def create_profile(self) -> None:
        name = simpledialog.askstring("Create profile", "Profile name", parent=self)
        if not name:
            return
        profile_id = slugify_profile_id(name)
        if any(profile["id"] == profile_id for profile in self.profiles):
            messagebox.showerror("Local SaaS Lab", "A profile with that id already exists.")
            return
        profile = {
            "id": profile_id,
            "project_id": self.current_project_var.get(),
            "name": name,
            "preset_id": "",
            "kind": "staff",
            "role": "custom",
            "route": "#/staff/login",
            "base_route": "#/staff/login",
            "landing_route": "#/",
            "launch_mode": self.launch_mode_var.get(),
            "login_email": "",
            "login_password": "",
            "qr_token": "",
            "locale": "en-US",
            "theme": "system",
            "tags": ["custom"],
            "notes": "",
            "metadata": {},
        }
        self.profiles.append(profile)
        self.store.save_profiles(self.profiles)
        self.refresh_all_views()

    def clone_profile_from_preset(self) -> None:
        presets = [preset for preset in self.presets if preset.get("project_id", "ncs") == self.current_project_var.get()]
        preset_names = [preset["name"] for preset in presets]
        choice = simpledialog.askstring("Clone preset", f"Preset name:\n{', '.join(preset_names)}", parent=self)
        if not choice:
            return
        preset = next((item for item in presets if item["name"].lower() == choice.lower()), None)
        if not preset:
            messagebox.showerror("Local SaaS Lab", "Preset not found.")
            return
        new_name = simpledialog.askstring("Clone preset", "New profile name", initialvalue=f"{preset['name']} Copy", parent=self)
        if not new_name:
            return
        new_id = slugify_profile_id(new_name)
        if any(profile["id"] == new_id for profile in self.profiles):
            messagebox.showerror("Local SaaS Lab", "A profile with that id already exists.")
            return
        self.profiles.append(
            {
                "id": new_id,
                "project_id": preset["project_id"],
                "name": new_name,
                "preset_id": preset["id"],
                "kind": preset["kind"],
                "role": preset["role"],
                "route": preset["route"],
                "base_route": preset["base_route"],
                "landing_route": preset["landing_route"],
                "launch_mode": preset["launch_mode"],
                "login_email": preset["login_email"],
                "login_password": preset["login_password"],
                "qr_token": preset["qr_token"],
                "locale": preset["locale"],
                "theme": preset["theme"],
                "tags": list(preset.get("tags", [])),
                "notes": "",
                "metadata": dict(preset.get("metadata", {})),
            }
        )
        self.store.save_profiles(self.profiles)
        self.refresh_all_views()

    def edit_profile(self) -> None:
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("Local SaaS Lab", "Select a profile first.")
            return
        name = simpledialog.askstring("Edit profile", "Profile name", initialvalue=profile["name"], parent=self)
        if not name:
            return
        route = simpledialog.askstring("Edit profile", "Default route or URL", initialvalue=profile["route"], parent=self)
        if not route:
            return
        notes = simpledialog.askstring("Edit profile", "Notes", initialvalue=profile.get("notes", ""), parent=self)
        profile["name"] = name
        profile["route"] = route
        profile["notes"] = notes or ""
        self.store.save_profiles(self.profiles)
        self.refresh_all_views()

    def copy_profile_details(self) -> None:
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("Local SaaS Lab", "Select a profile first.")
            return
        lines = [
            profile["name"],
            f"Route: {profile['route']}",
            f"Landing: {profile.get('landing_route', '-')}",
            f"Email: {profile.get('login_email', '-')}",
            f"Password: {profile.get('login_password', '-')}",
            f"QR token: {profile.get('qr_token', '-')}",
        ]
        payload = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(payload)
        self.status_var.set(f"Copied details for {profile['name']}")

    def close_selected_session(self) -> None:
        selected = self.sessions_tree.selection()
        if not selected:
            profile = self.get_selected_profile()
            if profile:
                selected = [session["id"] for session in self._combined_sessions() if session["profile_id"] == profile["id"]]
            if not selected:
                messagebox.showinfo("Local SaaS Lab", "Select an active session or a launched profile.")
                return
        closed_any = False
        for session_id in selected:
            preserved = self._preserved_runtime_sessions.get(session_id)
            if preserved:
                runtime_bundle_id = preserved.get("runtime_bundle_id", "")
                runtime_handle = preserved.get("runtime_handle")
                self.runtime_engine.close_actor_session(
                    preserved["runtime"],
                    log_callback=lambda message: self._append_runner_log(f"[keep-open] {message}"),
                )
                self._preserved_runtime_sessions.pop(session_id, None)
                if runtime_handle and runtime_bundle_id and not any(
                    item.get("runtime_bundle_id") == runtime_bundle_id for item in self._preserved_runtime_sessions.values()
                ):
                    self.runtime_engine.stop_playwright_runtime(
                        runtime_handle,
                        log_callback=lambda message: self._append_runner_log(f"[keep-open] {message}"),
                    )
                closed_any = True
                continue
            session = next((item for item in self.active_sessions if item["id"] == session_id), None)
            if session and close_pid(int(session["pid"])):
                closed_any = True
        self.refresh_active_sessions()
        if closed_any:
            self.status_var.set("Closed selected session(s).")

    def reset_selected_profile(self) -> None:
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("Local SaaS Lab", "Select a profile first.")
            return
        if self._has_any_session_for_profile(profile["id"]):
            messagebox.showwarning("Local SaaS Lab", "Close active sessions for this profile before resetting it.")
            return
        if not messagebox.askyesno("Reset profile", f"Reset isolated Chrome data for {profile['name']}?"):
            return
        delete_profile_dir(profile_data_dir(CHROME_DATA_DIR, profile["id"]), CHROME_DATA_DIR)
        self.status_var.set(f"Reset profile data for {profile['name']}")

    def delete_selected_profile(self) -> None:
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("Local SaaS Lab", "Select a profile first.")
            return
        if self._has_any_session_for_profile(profile["id"]):
            messagebox.showwarning("Local SaaS Lab", "Close active sessions for this profile before deleting it.")
            return
        if not messagebox.askyesno("Delete profile", f"Delete profile {profile['name']} and its isolated Chrome data?"):
            return
        delete_profile_dir(profile_data_dir(CHROME_DATA_DIR, profile["id"]), CHROME_DATA_DIR)
        self.profiles = [item for item in self.profiles if item["id"] != profile["id"]]
        self.store.save_profiles(self.profiles)
        self.refresh_all_views()
        self.status_var.set(f"Deleted profile {profile['name']}")

    def refresh_active_sessions(self) -> None:
        self.active_sessions = self._reconcile_sessions(self.store.load_active_sessions())
        self._load_sessions_tree()

    def detect_chrome(self) -> None:
        path = detect_chrome_path()
        if path:
            self.chrome_path_var.set(path)
            self.status_var.set(f"Detected Chrome at {path}")
        else:
            messagebox.showwarning("Local SaaS Lab", "Chrome was not detected automatically.")

    def browse_chrome(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Chrome executable",
            filetypes=[("Chrome", "chrome.exe"), ("Executable", "*.exe"), ("All files", "*.*")],
        )
        if path:
            self.chrome_path_var.set(path)

    def save_settings(self) -> None:
        self.app_config["base_url"] = self.base_url_var.get().strip()
        self.app_config["chrome_path"] = self.chrome_path_var.get().strip()
        self.app_config["default_launch_mode"] = self.launch_mode_var.get().strip()
        self.app_config["default_window_size"] = self.window_size_var.get().strip()
        self.app_config["current_project"] = self.current_project_var.get().strip()
        self.app_config["keep_windows_open_after_run"] = self.keep_windows_open_var.get()
        self.app_config["artifacts_open_after_run"] = self.auto_open_artifact_var.get()
        self.store.save_app_config(self.app_config)
        self.adapter = get_adapter(self.current_project_var.get())
        self.refresh_all_views()
        self.status_var.set("Saved lab settings.")

    def open_selected_artifact_folder(self) -> None:
        selection = self.artifacts_tree.selection()
        if not selection:
            messagebox.showinfo("Local SaaS Lab", "Select a run first.")
            return
        run = next((item for item in self.run_history if item["id"] == selection[0]), None)
        if not run or not run.get("artifact_dir"):
            messagebox.showinfo("Local SaaS Lab", "This run does not have an artifact folder yet.")
            return
        self._open_path(run["artifact_dir"])

    def open_latest_artifact_for_selected_scenario(self) -> None:
        scenario = self.get_selected_scenario()
        if not scenario:
            messagebox.showinfo("Local SaaS Lab", "Select a scenario first.")
            return
        run = next((item for item in self._filtered_runs() if item["scenario_id"] == scenario["id"] and item.get("artifact_dir")), None)
        if not run:
            messagebox.showinfo("Local SaaS Lab", "No artifact found yet for this scenario.")
            return
        self._open_path(run["artifact_dir"])

    def open_selected_summary(self) -> None:
        run = self._get_selected_run()
        if not run or not run.get("artifact_dir"):
            messagebox.showinfo("Local SaaS Lab", "Select a run with an artifact folder first.")
            return
        self._open_path(str(Path(run["artifact_dir"]) / "summary.md"))

    def open_selected_best_evidence(self) -> None:
        run = self._get_selected_run()
        if not run:
            messagebox.showinfo("Local SaaS Lab", "Select a run first.")
            return
        best = next(iter(run.get("best_evidence", [])), None)
        if not best or not best.get("path"):
            messagebox.showinfo("Local SaaS Lab", "This run does not have a best-evidence screenshot yet.")
            return
        self._open_path(best["path"])

    def _open_path(self, target: str) -> None:
        path = Path(target)
        if not path.exists():
            messagebox.showerror("Local SaaS Lab", f"Path does not exist:\n{target}")
            return
        os.startfile(str(path))  # type: ignore[attr-defined]

    def _get_selected_run(self):
        selection = self.artifacts_tree.selection()
        if not selection:
            return None
        return next((item for item in self.run_history if item["id"] == selection[0]), None)

    def clear_selected_run_history(self) -> None:
        selected = list(self.artifacts_tree.selection())
        if not selected:
            messagebox.showinfo("Local SaaS Lab", "Select one or more run-history entries first.")
            return
        decision = messagebox.askyesnocancel(
            "Clear selected run history",
            "Remove the selected run-history entries?\n\nYes = also delete linked artifacts\nNo = keep artifacts on disk\nCancel = abort",
        )
        if decision is None:
            return
        self._clear_run_history(run_ids=selected, delete_artifacts=decision)

    def clear_all_run_history(self) -> None:
        runs = self._filtered_runs()
        if not runs:
            messagebox.showinfo("Local SaaS Lab", "There is no run history to clear.")
            return
        decision = messagebox.askyesnocancel(
            "Clear all run history",
            "Remove all run-history entries for the current project?\n\nYes = also delete linked artifacts\nNo = keep artifacts on disk\nCancel = abort",
        )
        if decision is None:
            return
        self._clear_run_history(run_ids=[run["id"] for run in runs], delete_artifacts=decision)

    def _clear_run_history(self, *, run_ids: list[str], delete_artifacts: bool) -> None:
        try:
            self.run_history, removed = prune_run_history(self.run_history, run_ids, delete_artifacts=delete_artifacts)
        except Exception as exc:  # noqa: BLE001 - keep the console honest and safe
            messagebox.showerror("Local SaaS Lab", str(exc))
            return
        self.store.save_run_history(self.run_history)
        self._load_artifacts_tree()
        self._render_run_details()
        if removed:
            artifact_note = " and deleted their artifacts" if delete_artifacts else ""
            self.status_var.set(f"Cleared {removed} run-history entrie(s){artifact_note}.")

    def _append_runner_log(self, line: str) -> None:
        if not line:
            return
        self.runner_log_text.configure(state="normal")
        self.runner_log_text.insert("end", f"{line}\n")
        self.runner_log_text.see("end")
        self.runner_log_text.configure(state="disabled")

    def _format_step_event_line(self, event: dict) -> str:
        parts = [
            f"[step {event.get('index', 0)}/{event.get('total_steps', 0)}]",
            event.get("actor", "-"),
            "::",
            event.get("title", "-"),
            f"({event.get('action', '-')})",
            "->",
            event.get("status", "-"),
        ]
        if event.get("current_url"):
            parts.append(f"@ {event['current_url']}")
        if event.get("reason"):
            parts.append(f"| {event['reason']}")
        if event.get("resolution"):
            parts.append(f"| resolution={event['resolution']}")
        return " ".join(parts)

    def _best_evidence_label(self, run_record: dict) -> str:
        first = next(iter(run_record.get("best_evidence", [])), None)
        if not first:
            return "-"
        return f"{first.get('label', '-')} ({first.get('type', '-')})"


def main() -> None:
    app = LocalSaasLabApp()
    app.mainloop()
