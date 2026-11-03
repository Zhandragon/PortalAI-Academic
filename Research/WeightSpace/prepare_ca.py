import ssl,sys
from pathlib import Path
root=Path(__file__).resolve().parents[3];sys.path.insert(0,str(root/'Agent'))
from web_tls import default_context
certs=default_context().get_ca_certs(binary_form=True)
out=Path(__file__).parent/'trusted-ca.pem'
out.write_text(''.join(ssl.DER_cert_to_PEM_cert(c) for c in certs),encoding='ascii')
print('Exported existing verified TLS trust for the research CLI:',len(certs),'public CA certificates')
