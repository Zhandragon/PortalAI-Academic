"""Themed record actions bound to the right-clicked row, never a stale selection."""
import sys
from themed_popup_menu import ThemedPopupMenu


class RecordContextMenu:
    def __init__(self, sheet, tree, items, *, title):
        self.sheet=sheet;self.tree=tree;self.items=items;self.title=title
        self.menu=ThemedPopupMenu(sheet.winfo_toplevel(),lambda:sheet.skin.colors)
        tree.bind('<Button-3>',self.open,add='+')
        if sys.platform=='darwin':tree.bind('<Control-Button-1>',self.open,add='+')
        tree.bind('<Shift-F10>',self.keyboard,add='+');tree.bind('<Menu>',self.keyboard,add='+')
        sheet.bind('<Destroy>',lambda event:self.close() if event.widget is sheet else None,add='+')

    def close(self):self.menu.close()

    def keyboard(self,event):
        ids=self.tree.selection()
        if ids:
            row=ids[0];box=self.tree.bbox(row)
            x,y=(box[0]+18,box[1]+box[3]) if box else (12,12)
            self.show(row,self.tree.winfo_rootx()+x,self.tree.winfo_rooty()+y)
        return 'break'

    def open(self,event):
        row=self.tree.identify_row(event.y)
        if row:self.show(row,event.x_root,event.y_root)
        else:self.close()
        return 'break'

    def show(self,row,x,y):
        if not self.tree.exists(row):return
        self.tree.selection_set(row);self.tree.focus(row);self.tree.focus_set()
        entries=[]
        for item in self.items(row):
            if item is None:entries.append(None);continue
            entry=dict(item);callback=entry.get('command')
            def invoke(command=callback,record=row):
                if not self.sheet.winfo_exists() or not self.tree.exists(record):return
                self.tree.selection_set(record);self.tree.focus(record)
                if command:command()
            entry['command']=invoke;entries.append(entry)
        self.menu.show(x,y,entries,title=self.title)
