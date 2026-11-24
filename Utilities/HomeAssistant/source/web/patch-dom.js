// Reconcile application-owned, escaped markup without remounting live elements.
// Never pass unescaped device text or remote HTML to this function.
export function patchMarkup(parent, html) {
  const template=document.createElement('template'); template.innerHTML=html;
  const sync=(target,source) => {
    let index=0;
    for (const wanted of [...source.childNodes]) {
      let current=target.childNodes[index];
      // Preserve message/media nodes when the bounded transcript window advances.
      if(wanted.nodeType===Node.ELEMENT_NODE&&wanted.hasAttribute('data-message')){
        const key=wanted.getAttribute('data-message');
        const match=[...target.childNodes].slice(index).find(n=>n.nodeType===Node.ELEMENT_NODE&&n.nodeName===wanted.nodeName&&n.getAttribute('data-message')===key);
        if(match&&match!==current){target.insertBefore(match,current||null);current=match;}
        else if(!match&&current?.getAttribute?.('data-message')!==key){target.insertBefore(wanted.cloneNode(true),current||null);index++;continue;}
      }
      if (!current) target.append(wanted.cloneNode(true));
      else if (current.nodeType!==wanted.nodeType || current.nodeName!==wanted.nodeName) current.replaceWith(wanted.cloneNode(true));
      else if (wanted.nodeType===Node.TEXT_NODE) { if (current.data!==wanted.data) current.data=wanted.data; }
      else if (wanted.nodeType===Node.ELEMENT_NODE) {
        for (const attr of [...current.attributes]) if (!wanted.hasAttribute(attr.name)) current.removeAttribute(attr.name);
        for (const attr of wanted.attributes) if (current.getAttribute(attr.name)!==attr.value) current.setAttribute(attr.name,attr.value);
        // RichChat owns this slot, including expanded records still streaming.
        if (!wanted.hasAttribute('data-rich-pending')) sync(current,wanted);
      }
      index++;
    }
    while (target.childNodes.length>index) target.lastChild.remove();
  };
  sync(parent,template.content);
}
