"""Use the existing compact chat controller for a portrait phone viewer."""


class RemoteLayout:
    def __init__(self,app,compact,show_tab,selected_tab,available=lambda:True):
        self.app=app;self.compact=compact;self.show_tab=show_tab;self.selected_tab=selected_tab
        self.phone=False;self.previous=None;self.target=(500,700)
        self.expanded_geometry=compact._expanded_geometry
        self.panel=compact.native_chat_panel
        self.available=available

    def check_available(self):
        if not self.available() or any(not d.closed for d in getattr(self.app,'_portalai_account_dialogs',())):
            raise PermissionError('Complete the account or shutdown dialog first')
        grab=self.app.grab_current()
        if grab is not None:raise PermissionError('Complete the open dialog first')

    def trim_phone(self):
        if not self.phone:return
        self.panel._set_history_collapsed(True,persist=False)
        self.panel.composer_shell.grid_remove()  # Compact's proxy is the composer.

    def send_chat(self,text):
        if not self.phone:raise RuntimeError('Direct chat composer is available in portrait chat view')
        if not isinstance(text,str) or not text.strip() or len(text)>8192:raise ValueError('Enter a message of up to 8192 characters')
        self.check_available()
        self.panel._check_login()
        if self.panel.busy or self.panel._closing:raise RuntimeError('Wait for the current response or Stop before sending')
        self.compact._entry_var.set(text)
        self.compact._send_compact()  # The same existing NativeChat submit path.

    def apply(self,event):
        self.check_available()
        view=event.get('view')
        if view not in ('full','portrait_chat'):raise ValueError('Invalid remote view')
        phone=view=='portrait_chat'
        width=max(500,min(800 if phone else 1920,int(event['width'])))
        height=max(400,min(1200,int(event['height'])))
        self.target=(width,height)
        if phone:
            if not self.phone:
                self.previous={'active':self.compact.active,'expanded':self.compact.expanded,'tab':self.selected_tab.get('key'),
                               'history_collapsed':self.panel.history_collapsed,'composer_visible':bool(self.panel.composer_shell.winfo_manager())}
                self.phone=True
                self.compact._expanded_geometry=lambda:self.target
            self.show_tab('chat')
            if not self.compact.active:self.compact.enter()
            if not self.compact.expanded:self.compact.toggle_chat()
            self.compact._set_size(True)
            self.trim_phone();self.app.after(160,self.trim_phone)
        else:
            if self.phone:
                self.phone=False;self.compact._expanded_geometry=self.expanded_geometry
                # The requested landscape/desktop experience is the full GUI.
                if self.compact.active:self.compact.exit()
                previous=self.previous or {};self.previous=None
                self.panel._set_history_collapsed(previous.get('history_collapsed',False),persist=False)
                if previous.get('composer_visible'):self.panel.composer_shell.grid()
                if previous.get('tab'):self.show_tab(previous['tab'])
            elif self.compact.active:self.compact.exit()
        self.app.deiconify();self.app.geometry(f'{width}x{height}')


def install(app,compact,show_tab,selected_tab,available=lambda:True):
    controller=RemoteLayout(app,compact,show_tab,selected_tab,available)
    app._portalai_remote_layout=controller.apply
    app._portalai_remote_chat=controller.send_chat
    pending=getattr(app,'_portalai_remote_layout_pending',None)
    if pending:
        def ready():
            if not available() or any(not d.closed for d in getattr(app,'_portalai_account_dialogs',())):
                app.after(250,ready);return
            controller.apply(getattr(app,'_portalai_remote_layout_pending',pending))
        app.after_idle(ready)
    return controller
