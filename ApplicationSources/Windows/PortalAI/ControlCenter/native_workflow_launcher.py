"""Explicit launcher action registration; input never selects a Python symbol."""
def configure(app,scope):
    controller=getattr(app,'_portalai_native_workflow',None)
    if controller is None:return None
    callbacks={}
    def add(key,label,callback,pages):callbacks[key]=(label,callback,set(pages.split()))
    for key,label,name,pages in (
        ('controls_startup','Startup','start_components','controls'),
        ('controls_test','System Test','run_system_test','controls'),
        ('controls_diagnose','Full Component Diagnosis','diagnose','controls'),
        ('controls_tray','Minimize to tray','minimize_to_tray','controls'),
        ('controls_stop','Stop all components','stop_components','controls'),
        ('controls_exit','Exit PortalAI','begin_exit_portableai','controls accounts'),
        ('theme','Switch theme','toggle_theme','controls settings'),
        ('diagnostic','Run selected component diagnostic','show_or_run_component_diagnostic','maintenance runtime'),
        ('media_verify','Verify media stack','show_or_run_media_stack_verify','maintenance'),
        ('dependency','Dependency Isolation Test','show_dependency_probe_panel','maintenance'),
        ('cleanup','General Cleanup','show_general_cleanup_panel','maintenance'),
        ('root_cleanup','Root Declutter','show_or_run_root_hygiene','maintenance'),
        ('reference_audit','Reference Audit','show_or_run_root_reference_audit','maintenance'),
        ('readiness','Fresh-machine readiness','show_or_run_fresh_machine_validator','maintenance')):
        add(key,label,scope[name],pages)
    add('storage_audit','Storage Audit',lambda:scope['show_or_run_storage_audit'](False),'maintenance')
    add('duplicate_scan','Deep Duplicate Scan',lambda:scope['show_or_run_storage_audit'](True),'maintenance')
    for kind,label in [('webcache','Delete Web Cache…'),('outputs','Delete All Outputs…'),('conversations','Delete Conversations + Memory…')]:
        add('delete_'+kind,label,lambda kind=kind:scope['show_maintenance_delete_confirm'](kind),'maintenance')
    for index,name in enumerate(scope['diag_choices']):
        add('diagnose_'+str(index),'Diagnose '+name,scope['_select_component_diagnostic'](name),'runtime installed')
    chat=scope['native_chat_panel']
    if chat is not None:
        for key,label,name in (
            ('chat_new','New chat','new_chat'),('chat_isolated','New isolated chat','new_isolated_chat'),
            ('chat_rename','Rename conversation…','rename_chat'),('chat_delete','Delete conversation…','delete_chat'),
            ('chat_edit','Edit last user message…','edit_last_user'),('chat_branch','Branch conversation…','open_branch_panel'),
            ('chat_regenerate','Regenerate last response','regenerate_last'),('chat_stop','Stop chat','stop_generation'),
            ('chat_memory','Selective memory…','open_memory_panel'),('chat_contribution','Toggle contribution','toggle_current_chat_memory'),
            ('chat_recall','Toggle recall','toggle_current_chat_recall'),('chat_preferences','Chat Preferences…','open_settings'),
            ('chat_instructions','Instructions…','open_instructions'),('chat_mic','Microphone (Aoostar)','toggle_mic'),
            ('chat_conversation','Hands-free conversation (Aoostar)','toggle_conversation_mode'),
            ('chat_clear_attachments','Clear pending attachments','clear_attachments'),('chat_manage_attachments','Manage attachments…','manage_attachments'),
            ('chat_copy','Copy last answer on Aoostar','copy_last_answer'),('chat_validate','Validate chat state','open_frontend_validation')):
            add(key,label,getattr(chat,name),'chat')
        from native_history import open_history
        add('chat_history','Browse and search all chats',lambda:open_history(controller),'chat')
        add('chat_include_selected','Include selected chats in memory',lambda:chat._set_selected_memory_included(True),'chat')
        add('chat_exclude_selected','Exclude selected chats from memory',lambda:chat._set_selected_memory_included(False),'chat')
        add('chat_ptt_begin','Start push-to-talk on Aoostar',chat._ptt_press,'chat')
        add('chat_ptt_end','Release push-to-talk on Aoostar',chat._ptt_release,'chat')
        add('chat_collapse_trace','Hide all tool trace blocks',chat.collapse_all_trace_blocks,'chat')
        zoom=getattr(chat,'chat_zoom',None)
        if zoom is not None:
            add('chat_zoom_in','Zoom Aoostar chat in',lambda:zoom.set_percent(zoom.percent+10),'chat')
            add('chat_zoom_out','Zoom Aoostar chat out',lambda:zoom.set_percent(zoom.percent-10),'chat')
            add('chat_zoom_reset','Reset Aoostar chat zoom',lambda:zoom.set_percent(100),'chat')
    # PersistencePage owns these real navigation buttons; the widget adapter already exposes them.
    # Registering aliases here duplicated both buttons in the HA native workflow.
    persistence=scope['persistence_page']
    # Local tabs can exceed the versioned HA page inventory. Export only
    # protocol pages; Controller.configure still rejects missing required pages
    # and safety actions before advertising support.
    from native_workflow_protocol import PAGES
    pages={key:page for key,page in scope['tab_pages'].items() if key in PAGES}
    controller.configure(pages=pages,callbacks=callbacks,chat=chat,settings=scope['settings_page'])
    bylabel={label:key for key,(label,_,_) in callbacks.items()}
    controller.fixed_widgets={w:bylabel[str(w.cget('text'))] for w in scope['buttons'] if str(w.cget('text')) in bylabel}
    if chat is not None:controller.fixed_widgets[chat.stop_btn]='chat_stop'
    controller.launcher_modal=lambda:scope['launcher_panel_state'].get('overlay')
    controller.persistence=persistence
    # The audit and per-feature report control activation. Do not announce the
    # complete protocol merely because this registration module imported.
    controller.adapter.publish_endpoint()
    return controller
