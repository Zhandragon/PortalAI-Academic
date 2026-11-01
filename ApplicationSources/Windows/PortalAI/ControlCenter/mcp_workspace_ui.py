"""On-demand MCP sign-in and resource/prompt dialogs."""
import json
import queue
from tkinter import ttk
from internal_sheet import InternalSheet


def oauth_dialog(panel):
    panel.admin();cid=panel.selected(panel.servers);connection=panel.connections.load(cid)
    sheet=InternalSheet(panel,'MCP sign-in',panel.skin.colors);skin=sheet.skin;p=sheet.content
    skin.label(p,'Register a public/native OAuth client with the provider. Callback path: /portalai-oauth/callback on 127.0.0.1. No client secret is stored.').pack(fill='x')
    fields={}
    for key,label,default in (('issuer','Issuer URL',''),('client_id','Registered public client ID',''),('scope','Requested scopes',''),('callback_port','Callback port (0 = automatic)','0')):
        skin.label(p,label).pack(fill='x');entry=skin.entry(p,str(connection.get('oauth',{}).get(key,default)));entry.pack(fill='x');fields[key]=entry
    def signin():
        config={k:v.get().strip() for k,v in fields.items()};config['callback_port']=int(config['callback_port'])
        panel.connections.configure_oauth(cid,config)
        sheet.destroy()
        if not hasattr(panel,'oauth_urls'):panel.oauth_urls=queue.Queue(maxsize=1)
        panel.job(lambda:panel.connections.sign_in(cid,lambda target:panel.oauth_urls.put_nowait(target)))
    def signout():panel.connections.sign_out(cid);sheet.destroy();panel.show('Local sign-in tokens removed. Revoke provider access at the provider if needed.')
    skin.button(p,'Save configuration and sign in',lambda:panel.invoke(signin)).pack(side='left',pady=8)
    skin.button(p,'Sign out locally',lambda:panel.invoke(signout)).pack(side='left',padx=5,pady=8)


def content_dialog(panel):
    panel.admin();cid=panel.selected(panel.servers)
    sheet=InternalSheet(panel,'MCP resources and prompts',panel.skin.colors);skin=sheet.skin;p=sheet.content
    skin.label(p,'Allow catalog/content reads from this server. Returned content remains untrusted; prompts do not run tools or change permissions.').pack(fill='x')
    rows=ttk.Treeview(p,columns=('kind','name','key'),show='headings',height=7)
    for key in ('kind','name','key'):rows.heading(key,text=key);rows.column(key,width=140)
    rows.pack(fill='both',expand=True);sheet.style_tree(rows);items={}
    skin.label(p,'Prompt arguments JSON (text values)').pack(fill='x');arguments=skin.entry(p,'{}');arguments.pack(fill='x')
    def permit(value):panel.connections.allow_content(cid,value);panel.show('Resource/prompt reads '+('allowed.' if value else 'disabled.'))
    def show(result):
        if not sheet.winfo_exists():return
        rows.delete(*rows.get_children());items.clear()
        kind,values=result
        for i,row in enumerate(values):
            key=row.get('uri') if kind=='resources' else row['name'];items[str(i)]=(kind,key)
            rows.insert('','end',iid=str(i),values=(kind,row.get('name',key),key))
    def catalog(kind):panel.job(lambda:(kind,panel.connections.content(cid,kind)),show)
    def read():
        chosen=rows.selection()
        if len(chosen)!=1:raise ValueError('Choose one catalog item')
        kind,key=items[chosen[0]];args=json.loads(arguments.get())
        panel.job(lambda:panel.connections.content(cid,kind,key,args))
    from ui_extensions import ResponsiveFlow
    bar=ResponsiveFlow(p,bg=skin.colors['panel'],hgap=4,vgap=4);bar.pack(fill='x')
    for title,fn in [('Allow reads',lambda:permit(True)),('Disable reads',lambda:permit(False)),('Resources',lambda:catalog('resources')),('Prompts',lambda:catalog('prompts')),('Read selected',read)]:
        bar.add(skin.button(bar,title,lambda f=fn:panel.invoke(f)))
