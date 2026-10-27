"""Launcher-owned Utilities subpanel; utilities retain independent processes."""
from account_ui import _Dialog
import suite_utilities
import sys


def utility_button_help(dialog, button, topic):
    """Public, read-only help remains available without unlocking an account."""
    from help_catalog import TOPICS
    from themed_popup_menu import ThemedPopupMenu
    # Keep the popup inside the login card's allowed widget subtree.
    menu = ThemedPopupMenu(dialog.surface.card, lambda: dialog.colors)
    record = TOPICS[topic]
    def explain():
        if dialog.closed or dialog.busy:
            return
        info = _Dialog(dialog.win, record['title'], dialog.colors)
        info.label(record['body'])
        info.button('Close', info.close)
    def context(event):
        if not dialog.closed and not dialog.busy:
            x = getattr(event, 'x_root', button.winfo_rootx())
            y = getattr(event, 'y_root', button.winfo_rooty()+button.winfo_height())
            menu.show(x, y, [{'label': 'What this does…', 'command': explain}], title=record['title'])
        return 'break'
    button.bind('<Button-3>', context, add='+')
    button.bind('<Shift-F10>', context, add='+')
    if sys.platform == 'darwin': button.bind('<Control-Button-1>', context, add='+')
    button.bind('<Destroy>', lambda event: menu.close() if event.widget is button else None, add='+')


# Retain the login helper name for callers sharing the guarded dialog.
login_button_help = utility_button_help


def show_utilities(parent, root, colors):
    dialog = _Dialog(parent, 'Utilities', colors)
    detected = suite_utilities.current_platform()
    dialog.label('Utilities for ' + detected, bold=True)
    dialog.label('These open as separate programs. Optional downloads are selected in the PortalAI suite installer.', muted=True)
    def perform(operation):
        try:
            operation()
            dialog.status.set('Opened separately.')
        except (OSError, ValueError, RuntimeError) as exc:
            dialog.status.set(str(exc))
    for key, title in (('abliterator', 'PortalAI Abliterator'), ('projection', 'PortalAI Home Assistant Projection')):
        if key == 'abliterator' and suite_utilities.edition(root) != 'Full':
            continue
        button = dialog.button(title, lambda key=key: perform(lambda: suite_utilities.launch(root, key)))
        utility_button_help(dialog, button, 'suite_' + key)
        if key == 'abliterator' and detected != 'Windows':
            button.configure(state='disabled')
            dialog.label('Abliterator currently has a Windows package only.', muted=True)
    for edition in suite_utilities.editions(root):
        dialog.label(edition + ' installers', bold=True)
        for system in suite_utilities.PLATFORMS:
            button = dialog.button('Locate ' + system + ' Installer',
                                   lambda edition=edition, system=system: perform(lambda: suite_utilities.reveal(root, edition, system)))
            utility_button_help(dialog, button, 'suite_installers')
    dialog.status_line()
    dialog.button('Close', dialog.close)
    return dialog


def add_login_utilities(dialog, controller, *, recovery_parent=None, reset_parent=None):
    """No session or writer operation may be active when requesting this exit."""
    def request(action):
        if dialog.busy or dialog.closed:
            return
        try:
            suite_utilities.request_after_exit(controller.root, action)
        except (OSError, ValueError, RuntimeError) as exc:
            dialog.status.set(str(exc))
            return
        dialog.close()
    recovery = dialog.button('Crash recovery', lambda: request('recover'))
    reset = dialog.button('Wipe all accounts…', lambda: request('reset'), tone='danger')
    for button, parent, anchor in ((recovery, recovery_parent, 'w'), (reset, reset_parent, 'e')):
        if parent is not None:
            button.pack_forget(); button.pack(in_=parent, anchor=anchor, pady=3)
    login_button_help(dialog, recovery, 'login_crash_recovery')
    login_button_help(dialog, reset, 'wipe_all_accounts')
