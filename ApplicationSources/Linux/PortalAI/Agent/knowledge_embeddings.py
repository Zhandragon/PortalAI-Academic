"""Pinned local MiniLM CPU embeddings; no network, Torch, or shared model service."""
import hashlib
import json
from pathlib import Path
import sys
import unicodedata


def packages(root):
    roots=[Path(root)/p for p in ('Runtime/Knowledge/packages','Voice/Piper/packages',
        'Runtime/LinuxPackages/extras','Runtime/SciencePackages','Runtime/ScienceExtras/packages')]
    for p in reversed(roots):
        if p.is_dir() and str(p) not in sys.path:sys.path.insert(0,str(p))
    return roots


class Embeddings:
    def __init__(self, root):
        self.root=Path(root);allowed=packages(root)
        import numpy as np
        import onnxruntime as ort
        for module in (np,ort):
            if not any(Path(module.__file__).resolve().is_relative_to(p.resolve()) for p in allowed):
                raise RuntimeError('Knowledge embeddings require the portable runtime')
        folder=self.root/'Runtime/Knowledge/model'
        manifest=json.loads((folder/'manifest.json').read_text())
        if set(manifest['files'])!={'model.onnx','vocab.txt'}:raise ValueError('Incomplete embedding manifest')
        for name,expected in manifest['files'].items():
            if name not in ('model.onnx','vocab.txt'):raise ValueError('Invalid embedding manifest')
            with (folder/name).open('rb') as f:
                if hashlib.file_digest(f,'sha256').hexdigest()!=expected:raise ValueError('Embedding asset checksum mismatch')
        self.fingerprint=manifest['files']['model.onnx']
        self.vocab={word:i for i,word in enumerate((folder/'vocab.txt').read_text(encoding='utf-8').splitlines())}
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(folder/'model.onnx'),options,providers=['CPUExecutionProvider'])
        self.np=np

    def tokens(self, text):
        # BERT uncased BasicTokenizer followed by WordPiece, with CLS/SEP.
        clean=[]
        for c in str(text):
            code=ord(c);cat=unicodedata.category(c)
            if c.isspace():clean.append(' ')
            elif code in (0,0xfffd) or cat in ('Cc','Cf'):continue
            elif 0x4e00<=code<=0x9fff or 0x3400<=code<=0x4dbf or 0x20000<=code<=0x2fa1f:clean.extend((' ',c,' '))
            else:clean.append(c)
        words=[]
        for token in ''.join(clean).split():
            token=''.join(c for c in unicodedata.normalize('NFD',token.lower()) if unicodedata.category(c)!='Mn')
            current=''
            for c in token:
                if unicodedata.category(c).startswith('P') or 33<=ord(c)<=47 or 58<=ord(c)<=64 or 91<=ord(c)<=96 or 123<=ord(c)<=126:
                    if current:words.append(current);current=''
                    words.append(c)
                else:current+=c
            if current:words.append(current)
        ids=[self.vocab['[CLS]']]
        for word in words:
            start=0;pieces=[]
            if len(word)>100:pieces=[self.vocab['[UNK]']];start=len(word)
            while start<len(word):
                end=len(word)
                while end>start:
                    piece=('##' if start else '')+word[start:end]
                    if piece in self.vocab:break
                    end-=1
                if end==start:pieces=[self.vocab['[UNK]']];break
                pieces.append(self.vocab[piece]);start=end
            ids.extend(pieces)
        return ids[:255]+[self.vocab['[SEP]']]

    def encode(self, texts, check=lambda:None):
        np=self.np;result=[]
        for offset in range(0,len(texts),16):
            check();rows=[self.tokens(t) for t in texts[offset:offset+16]]
            width=max(map(len,rows));ids=np.zeros((len(rows),width),dtype=np.int64);mask=np.zeros_like(ids)
            for i,row in enumerate(rows):ids[i,:len(row)]=row;mask[i,:len(row)]=1
            feed={'input_ids':ids,'attention_mask':mask,'token_type_ids':np.zeros_like(ids)}
            feed={x.name:feed[x.name] for x in self.session.get_inputs()}
            hidden=self.session.run(None,feed)[0]
            vectors=(hidden*mask[:,:,None]).sum(axis=1)/mask.sum(axis=1)[:,None]
            vectors/=np.maximum(np.linalg.norm(vectors,axis=1,keepdims=True),1e-12)
            result.extend(vectors.astype('float32').tolist());check()
        return result
