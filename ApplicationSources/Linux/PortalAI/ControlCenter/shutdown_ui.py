"""Visible account shutdown progress; never unlocks or destroys private surfaces."""
import time

from account_presentation import lock_account_surfaces
from account_ui import _Dialog


class ShutdownStatus:
    def __init__(self, app, colors, retry):
        self.app = app
        self.colors = colors
        self.retry = retry
        self.dialog = None
        self.timer = None
        self.started = None
        self.failed = False

    def show(self):
        lock_account_surfaces(self.app, self.colors)
        if self.dialog is None or self.dialog.closed:
            self.dialog = _Dialog(self.app, 'Closing PortalAI safely', self.colors, startup=True)
            reminder = self.dialog.label('Keep this drive connected until PortalAI closes.', bold=True)
            description = self.dialog.label('Stopping background work and encrypting account files can take several minutes. The launcher will close only after the saved workspace has been verified.')
            self.phase = self.dialog.label('Preparing shutdown…')
            self.elapsed = self.dialog.label('')
            for label in (reminder, description, self.phase, self.elapsed):
                label.configure(fg=self.colors.get('muted', '#6E665E'))
            self.retry_button = self.dialog.button('Retry verified shutdown', self._retry, enabled=False,tone='danger')
            self.retry_button.pack_configure(anchor='e')
            self.dialog.status_line()
            self.dialog.set_close_handler(self._close_requested)
        self.dialog.show_locked()
        self.app.lift()

    def begin(self):
        self.show()
        self.failed = False
        self.started = time.monotonic()
        self.retry_button.configure(state='disabled')
        self.dialog.status.set('')
        self.phase.configure(text='Cancelling new work and releasing media devices…')
        self._tick()

    def update(self, message):
        self.show()
        self.phase.configure(text=str(message))

    def failure(self, error_type=None):
        self.show()
        previous_phase = self.phase.cget('text')
        seconds = max(0, int(time.monotonic()-(self.started or time.monotonic())))
        self.failed = True
        if self.timer is not None:
            self.app.after_cancel(self.timer)
            self.timer = None
        self.elapsed.configure(text=f'Stopped after: {seconds//60}:{seconds%60:02d}')
        import re
        code = str(error_type or '')
        if not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}', code): code = 'ShutdownError'
        self.phase.configure(text='Shutdown failed during: '+previous_phase+'\nError type: '+code)
        self.dialog.status.set('Private surfaces remain locked. Keep the drive connected and retry verified shutdown. Do not launch a second copy to recover this open session.')
        self.retry_button.configure(state='normal')

    def _retry(self):
        if self.failed:
            self.retry()

    def _close_requested(self):
        self.show()
        self.dialog.status.set('Use Retry verified shutdown to continue safely.' if self.failed else
                               'Shutdown is still in progress. Keep the drive connected; PortalAI will close when verification finishes.')

    def _tick(self):
        if self.timer is not None:
            self.app.after_cancel(self.timer)
        self.timer = None
        if self.failed or self.dialog is None or self.dialog.closed:
            return
        seconds = max(0, int(time.monotonic()-(self.started or time.monotonic())))
        self.elapsed.configure(text=f'Elapsed: {seconds//60}:{seconds%60:02d}')
        self.timer = self.app.after(1000, self._tick)

    def finish(self):
        if self.timer is not None:
            self.app.after_cancel(self.timer)
            self.timer = None
        if self.dialog is not None and not self.dialog.closed:
            self.dialog.close()
