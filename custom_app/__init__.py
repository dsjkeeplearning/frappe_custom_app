__version__ = "0.0.1"


def _apply_patches():
    try:
        from custom_app.overrides.budget import apply_budget_patch

        apply_budget_patch()
    except ImportError:
        # erpnext not yet importable (e.g. during bench build before app install)
        pass


_apply_patches()
