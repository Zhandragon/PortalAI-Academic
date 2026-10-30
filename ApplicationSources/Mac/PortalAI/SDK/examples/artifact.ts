import {Client} from '../typescript/portalai.js';
// Compile with your application's TypeScript toolchain. Supply credentials from
// your application's secret store, never embed them in an HTML artifact.
export async function example(baseURL:string,token:string) {
  const client=new Client(baseURL,token);
  const key=Client.newKey(); console.log('Retain request key:',key);
  return client.request('POST','/artifacts',{
    title:'Example counter',kind:'html',
    content:'<button onclick="this.textContent=Number(this.textContent)+1">0</button>'
  },{key});
}
