# XT30 Battery Mod: change MODE only, then paste the entire script in Lab.
MODE = 'INSTALL'  # INSTALL, STATUS, DISABLE, UNINSTALL
PAYLOAD_B64 = '__PAYLOAD_B64__'
import rm_define
loader = rm_define.__dict__['__builtins__']['__import__']
loader('builtins').exec(loader('base64').b64decode(PAYLOAD_B64), globals())
