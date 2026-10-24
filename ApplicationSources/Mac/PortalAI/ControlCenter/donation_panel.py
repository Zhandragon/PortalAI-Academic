"""Public donation information and explicit copy/open actions; no payment processing."""
from pathlib import Path
import tkinter as tk
import webbrowser

from elegant_native_ui import ElegantButton, ui_font
from ornate_ui import ConnectedBorder
from portal_frontend_v15136 import portal_display_font

SPONSOR_URL = 'https://github.com/sponsors/Zhandragon'
INTRODUCTION = (
    'PortalAI was initially developed over a month by one person, who is now continuing '
    'to improve its features and capabilities. If you find use from this program and '
    'would like to support its continued development, please consider donating, either '
    'via the Github Sponsors program or directly here via PayPal or crypto.'
)
DESTINATIONS = (
    ('PayPal', 'PayPal donation link', 'paypal.png',
     'https://www.paypal.com/qrcodes/managed/25c71b49-6280-4db1-a983-4db5f53183eb?utm_source=consweb_more'),
    ('Ethereum', 'Ethereum network · ETH', 'ethereum.png',
     '0x9C4D852279801fB4379b11698fD5835Fe275307D'),
    ('Polygon', 'Polygon network · POL', 'polygon.png',
     '0x9C4D852279801fB4379b11698fD5835Fe275307D'),
    ('Bitcoin', 'Bitcoin network · BTC', 'bitcoin.png',
     'bc1q24y4u2xe5pzk9pg3q7qyjty8vhxvp4nskunqle'),
)

# Exact QR module bounds in the supplied originals; presentation only. Keep the
# PNGs, module pixels, logos and encoded destinations unchanged.
QR_INTERIORS = {
    'ethereum.png': ((217, 221), (26, 27, 191, 192)),
    'polygon.png': ((215, 216), (24, 26, 189, 191)),
    'bitcoin.png': ((220, 221), (26, 26, 191, 191)),
}


def qr_photo(master, source):
    source = Path(source)
    original = tk.PhotoImage(master=master, file=str(source))
    interior = QR_INTERIORS.get(source.name)
    if interior and (original.width(), original.height()) == interior[0]:
        bounds = interior[1]
    else:
        # Retain the established PayPal scale, or show unrecognized artwork
        # intact rather than applying coordinates from a different image.
        if original.width() > 300:
            original = original.zoom(2, 2).subsample(5, 5)
        bounds = (0, 0, original.width(), original.height())
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    photo = tk.PhotoImage(master=master, width=max(230, width), height=max(230, height))
    photo.put('#ffffff', to=(0, 0, photo.width(), photo.height()))
    photo.tk.call(str(photo), 'copy', str(original), '-from', *bounds,
                  '-to', (photo.width() - width) // 2, (photo.height() - height) // 2)
    return photo


class DonationLink(tk.Button):
    """A quiet title-bar link using native keyboard/click button dispatch."""
    def __init__(self, parent, colors):
        super().__init__(parent, text='Donate', state='disabled', relief='flat',
                         overrelief='flat', bd=0, highlightthickness=0, padx=7, pady=0,
                         cursor='hand2', takefocus=1, font=(portal_display_font(parent), 11, 'bold'))
        self.apply_palette(colors)
        self.bind('<Return>', self._activate, add='+')
        self.bind('<KP_Enter>', self._activate, add='+')

    def _activate(self, _event=None):
        self.invoke()
        return 'break'

    def apply_palette(self, colors):
        background = colors.get('panel3', colors['panel'])
        rgb = self.winfo_rgb(background)
        dark = sum(rgb) < 3 * 32768
        foreground = '#72D8D2' if dark else '#007C83'
        self.configure(bg=background, activebackground=background, fg=foreground,
                       activeforeground='#A0EBE5' if dark else '#005D64',
                       disabledforeground=colors.get('muted', foreground))


def sponsor_button(parent, colors, *, command=None):
    """Opening the sponsor page is always a deliberate button action."""
    return ElegantButton(
        parent, text='Sponsor on GitHub', command=command or (lambda: webbrowser.open(SPONSOR_URL)),
        bg=colors['button'], fg=colors['accent'], activebackground=colors.get('button_hover', colors['button']),
        activeforeground=colors['text'], font=(portal_display_font(parent), 10, 'bold'),
        padx=20, pady=8, bd=0, cursor='hand2', takefocus=1,
    )


class DonationPanel(tk.Frame):
    def __init__(self, parent, root, colors):
        super().__init__(parent, bg=colors['bg'])
        self.root_path=Path(root)
        self.colors=dict(colors)
        self.images=[];self.borders=[];self.cards=[];self.palette_widgets=[]
        self.copy_buttons=[];self.qr_buttons=[];self.address_labels=[]
        self._columns=None
        self.pack(fill='both',expand=True,padx=20,pady=8)
        self.header=tk.Frame(self,bg=colors['bg']);self.header.pack(fill='x')
        self.brand_row=tk.Frame(self.header,bg=colors['bg']);self.brand_row.pack()
        self.wordmark=tk.Label(self.brand_row,bg=colors['bg'],bd=0)
        try:
            wordmark=tk.PhotoImage(master=self,file=str(self.root_path/'ControlCenter/Branding/PortalAI_Wordmark_Welcome_320.png'))
            self.images.append(wordmark);self.wordmark.configure(image=wordmark)
        except (OSError,tk.TclError):
            self.wordmark.configure(text='PortalAI',fg=colors['accent'],font=(portal_display_font(self),24,'bold'))
        self.wordmark.pack(side='left',pady=(0,2))
        try:
            image=tk.PhotoImage(master=self,file=str(self.root_path/'ControlCenter/Branding/PortableAI_Header_72.png'))
            self.images.append(image)
            emblem=tk.Label(self.brand_row,image=image,bg=colors['bg'],bd=0)
            emblem.pack(side='left',padx=(12,0),pady=(0,4));self.palette_widgets.append((emblem,'bg',None))
        except (OSError,tk.TclError):
            pass
        self.heading=self._label(self.header,'Support PortalAI',16,'accent',bold=True)
        self.heading.pack(pady=(0,4))
        self.intro=self._label(self,INTRODUCTION,10,'text',justify='center',wraplength=1000)
        self.intro.pack(fill='x',padx=12,pady=(0,6))
        self.sponsor=sponsor_button(self,colors);self.sponsor.pack(pady=(0,4))
        self.hint=self._label(self,'Scan a code, or click a code or its button to copy the destination.',9,'muted')
        self.hint.pack(pady=(0,6))
        self.grid_host=tk.Frame(self,bg=colors['bg']);self.grid_host.pack(fill='x')
        for index,(name,network,filename,value) in enumerate(DESTINATIONS):
            card=tk.Frame(self.grid_host,bg=colors['panel'],bd=0,highlightthickness=0)
            self.cards.append(card)
            border=ConnectedBorder(card,colors,radius=12,shine=False,filigree=False,simple=True)
            border.simple_radius=12
            self.borders.append(border)
            body=tk.Frame(card,bg=colors['panel'],bd=0)
            body.pack(fill='both',expand=True,padx=12,pady=10)
            self.palette_widgets.append((body,'panel',None))
            title=self._label(body,name,12,'text',bold=True,background='panel');title.pack(pady=(2,2))
            subtitle=self._label(body,network,9,'muted',background='panel');subtitle.pack(pady=(0,9))
            source=self.root_path/'ControlCenter/DonationAssets'/filename
            # Shared white canvases remove screenshot framing without editing QR pixels.
            try:
                photo=qr_photo(self,source)
                self.images.append(photo)
            except (OSError,tk.TclError):
                photo=None
            copy=lambda i=index:self.copy_destination(i)
            qr=tk.Button(body,image=photo,text='' if photo is not None else 'Copy destination',command=copy,bg='#ffffff',activebackground='#ffffff',
                         width=230,height=230,padx=0,pady=0,bd=0,highlightthickness=0,cursor='hand2',takefocus=0)
            qr.pack(pady=(0,8));self.qr_buttons.append(qr)
            display='paypal.com · personal donation link' if name=='PayPal' else value
            address=self._label(body,display,9,'muted',background='panel',wraplength=240,justify='center')
            address.pack(fill='x',pady=(0,8));address.bind('<Button-1>',lambda _event,i=index:self.copy_destination(i))
            address.configure(cursor='hand2');self.address_labels.append(address)
            button=ElegantButton(body,text='Copy PayPal link' if name=='PayPal' else 'Copy address',
                command=copy,bg=colors['button'],fg=colors['text'],activebackground=colors.get('button_hover', colors['button']),
                activeforeground=colors['text'],font=(portal_display_font(self),9,'bold'),
                padx=12,pady=7,bd=0,cursor='hand2',takefocus=1)
            button.pack(side='bottom',fill='x',pady=(4,0));self.copy_buttons.append(button)
        self.status=tk.StringVar(self,value='Thank you for supporting continued development.')
        self.status_label=self._label(self,'',9,'accent');self.status_label.configure(textvariable=self.status)
        self.status_label.pack(fill='x',pady=(6,2))
        self.bind('<Configure>',self._layout,add='+')
        self.after_idle(self._layout)

    def _label(self,parent,text,size,foreground,*,bold=False,background='bg',**kwargs):
        label=tk.Label(parent,text=text,bg=self.colors[background],fg=self.colors[foreground],bd=0,
            font=(portal_display_font(self) if bold else ui_font(self),size,'bold' if bold else 'normal'),**kwargs)
        self.palette_widgets.append((label,background,foreground))
        return label

    def _layout(self,event=None):
        width=max(1,self.winfo_width())
        columns=4 if width>=1120 else (2 if width>=580 else 1)
        self.intro.configure(wraplength=max(200,min(1100,width-32)))
        self.hint.configure(wraplength=max(200,width-24))
        if self._columns!=columns:
            self._columns=columns
            for i in range(4):self.grid_host.grid_columnconfigure(i,weight=1 if i<columns else 0,uniform='donations' if i<columns else '')
            for i,card in enumerate(self.cards):card.grid(row=i//columns,column=i%columns,sticky='nsew',padx=6,pady=6)
        for address in self.address_labels:address.configure(wraplength=max(200,width//columns-52))

    def copy_destination(self,index):
        name,network,filename,value=DESTINATIONS[index]
        self.clipboard_clear();self.clipboard_append(value)
        self.status.set(('PayPal link' if name=='PayPal' else name+' address')+' copied to clipboard.')

    def apply_palette(self,colors):
        self.colors=dict(colors)
        for widget in [self,self.header,self.brand_row,self.wordmark,self.grid_host]:widget.configure(bg=colors['bg'])
        for widget,bg,fg in self.palette_widgets:
            widget.configure(bg=colors[bg],**({'fg':colors[fg]} if fg else {}))
        for card in self.cards:card.configure(bg=colors['panel'])
        for border in self.borders:border.apply_palette(colors)
        for button in [self.sponsor,*self.copy_buttons]:
            button.configure(bg=colors['button'],fg=colors['accent'] if button is self.sponsor else colors['text'],
                             activebackground=colors.get('button_hover', colors['button']),activeforeground=colors['text'])
        self.wordmark.configure(fg=colors['accent'])
