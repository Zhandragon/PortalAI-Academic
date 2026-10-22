import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location('portalai_test_'+name,ROOT/'distribution/HomeAssistant'/ (name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
c=load('configure');i=load('install');finish=load('finish');yaml=c.yaml

class AutoSetupTests(unittest.TestCase):
    def test_new_ha_preserves_other_sections_and_creates_complete_portalai_setup(self):
        text='# My HA\r\ndefault_config:\r\nfrontend:\r\n  themes: !include_dir_merge_named themes\r\nautomation: !include automations.yaml\r\nscript: !include scripts.yaml\r\n'
        result=c.configure(text,'1'*32)
        self.assertTrue(result.startswith('# My HA\r\ndefault_config:\r\n'))
        self.assertIn('automation: !include automations.yaml\r\nscript: !include scripts.yaml\r\n',result)
        n=yaml.compose(result);front=c.get(n,'frontend')
        self.assertEqual(c.get(front,'themes').tag,'!include_dir_merge_named')
        for domain in c.DOMAINS:self.assertIsNotNone(c.get(n,domain))
        self.assertEqual(c.get(c.get(n,'panel_custom').value[0],'config').value[0][1].value,'1'*32)
        self.assertEqual(c.configure(result,'1'*32),result)
        dash=yaml.safe_load(c.dashboard('1'*32));self.assertEqual(len(dash['views']),3)
        self.assertIsInstance(dash['views'][0]['cards'][1]['device_id'],str)
    def test_existing_panels_modules_and_dashboards_preserved_no_duplicates(self):
        text='frontend: {extra_module_url: [/local/other.js, /local/portalai-quick-chat-v0.4.1.js]}\npanel_custom:\n  - name: another\n    url_path: other\n  - name: portalai-live-panel\n    url_path: portalai-native\nlovelace:\n  dashboards:\n    personal-dash: {mode: yaml, filename: personal.yaml}\nsensor: !include sensors.yaml\n'
        result=c.configure(text,'a'*32);n=yaml.compose(result)
        self.assertIn('sensor: !include sensors.yaml',result)
        self.assertEqual(len(c.get(n,'panel_custom').value),2)
        mods=c.get(c.get(n,'frontend'),'extra_module_url').value
        self.assertEqual([x.value for x in mods],['/local/other.js',*c.MODULES])
        self.assertIsNotNone(c.get(c.get(c.get(n,'lovelace'),'dashboards'),'personal-dash'))
    def test_ambiguous_yaml_refused_before_write(self):
        for text in ['frontend: !include frontend.yaml\n','frontend: {}\nfrontend: {}\n','panel_custom: !include panels.yaml\n','homeassistant:\n  packages: !include_dir_named packages\n','x: &value {}\nfrontend: *value\n','lovelace:\n  dashboards:\n    portalai-overview: {filename: mine.yaml}\n']:
            with self.subTest(text=text),self.assertRaises(ValueError):c.configure(text,'a'*32)
    def test_yaml_alias_upgrade_and_rollback_are_one_transaction(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);before=b'default_config:\n'
            (root/'configuration.yaml').write_bytes(before);(root/'www').mkdir()
            old=root/'www/portalai-projection-demand-v2.js';old.write_bytes(b'previous reconnect version')
            files={'www/portalai-live-v0.5.12.js':b'new native','www/portalai-quick-chat-v0.4.3.js':b'new quick','www/portalai-projection-v0.5.12.js':b'new desktop with reconnect'}
            files=i.automatic_setup(root,files,'b'*32)
            backup=i.install(root,files)
            self.assertEqual(old.read_bytes(),files['www/portalai-projection-v0.5.12.js'])
            self.assertIsNone(i.install(root,i.automatic_setup(root,dict(files),'b'*32)))
            i.rollback(root,backup)
            self.assertEqual((root/'configuration.yaml').read_bytes(),before)
            self.assertEqual(old.read_bytes(),b'previous reconnect version')
            self.assertFalse((root/'portalai/dashboard.yaml').exists())
    def test_invalid_device_id_does_not_generate_config(self):
        with self.assertRaises(ValueError):i.automatic_setup(Path('.'),{},i.PLACEHOLDER)
    def test_concurrent_configuration_edit_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'configuration.yaml';p.write_text('default_config:\n')
            files=i.automatic_setup(root,{},'a'*32)
            p.write_text('default_config:\n# owner changed this\n')
            with self.assertRaisesRegex(ValueError,'changed since'):i.install(root,files)
            self.assertIn('owner changed',p.read_text())
    def test_admin_finish_checks_origin_configuration_and_separate_pairing(self):
        for url in ['https://user:pass@example.org','https://example.org/?token=x','file:///etc/passwd','https://example.org/path']:
            with self.assertRaises(ValueError):finish.HomeAssistant(url,'fixture')
        api=finish.HomeAssistant('https://ha.example.org','fixture')
        with patch.object(api,'request',return_value={'result':'invalid'}):
            with self.assertRaises(ValueError):api.check()
        calls=[]
        api.request=lambda path,data=None:calls.append((path,data)) or {'result':'valid'}
        api.check();api.pair_projection({'device_id':'a'*32},'a'*32)
        self.assertEqual([p for p,d in calls],['/api/config/core/check_config','/api/services/portalai_projection/pair_device','/api/services/portalai_native/allow_state'])
        with self.assertRaises(ValueError):api.pair_projection({'device_id':'b'*32},'a'*32)
        with self.assertRaises(ValueError):finish.NoRedirect().redirect_request(None,None,None,None,None,None)
