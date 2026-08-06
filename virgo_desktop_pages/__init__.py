"""Virgo Desktop pages package — re-exports the page classes.

Split from the original virgo_desktop_pages.py monolith. External code
imports unchanged:  `from virgo_desktop_pages import ChatPage`.
"""
from .base import *  # noqa: F401,F403
from .base import (  # noqa: F401
    HERE, OUTDIR, icon, _beep, _set_layout_visible, _StopStream, _GuiStream,
)
from .pages_core import *  # noqa: F401,F403
from .pages_core import (  # noqa: F401
    _StopStream, _ImageDropHandler,
    _strip_think, _md_to_html, _chat_session_path, _load_recent_chat,
    _prompt_slug, _load_prompt_file, _write_prompt_file, _find_prompt_vars,
    _fill_prompt_vars, _CHAT_HISTORY_DIR,
)
from .pages_plugins import *  # noqa: F401,F403
from .pages_monitor import *  # noqa: F401,F403
from .pages_monitor import _GuiStream  # noqa: F401
from .pages_agents import *  # noqa: F401,F403
from .pages_agents import AgentCard  # noqa: F401
from .pages_bench import *  # noqa: F401,F403
from .pages_settings import *  # noqa: F401,F403
from .pages_settings import _live_ollama_models  # noqa: F401
from .pages_dashboard import *  # noqa: F401,F403
from .pages_dashboard import _xp_for_level  # noqa: F401
from .pages_recon import *  # noqa: F401,F403
from .pages_social import *  # noqa: F401,F403
from .pages_c2 import C2CommanderPage  # noqa: F401
from .pages_arena import AdversarialArenaPage  # noqa: F401
from .pages_experimental import *  # noqa: F401,F403
from .pages_experimental import (  # noqa: F401
    SonificationPage, DreamsPage, FlavorPage, GhostPage,
    ArchaeologyPage, EmpathyPage, AuditPage, MemesPage,
    StigmergyPage, DivergencePage,
)
from .pages_new import (  # noqa: F401
    PheromoneTrailPage,
    SoundscapePage,
    EmpathyUIPage,
    GhostReplayPage,
    DNAFingerprintPage,
    DreamVizPage,
    SwarmDashboardPage,
    PluginShellPage,
)
from .pages_features import (  # noqa: F401
    DiffusalPage,
    DebatePage,
    SelfHealPage,
)
from .pages_vibevoice import VibeVoicePage  # noqa: F401

