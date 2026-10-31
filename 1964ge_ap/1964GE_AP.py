from pathlib import Path
import json
import importlib
import os
import sys

START_DIRECTORY = Path.cwd()
STATE = Path(os.environ['LOCALAPPDATA']) / '1964GE_AP'
configuration = json.loads((STATE / 'settings.json').read_text(encoding='utf-8'))
archipelago = Path(configuration['archipelago'])
sys.dont_write_bytecode = True
sys.frozen = True
sys.executable = str(archipelago / 'ArchipelagoLauncher.exe')
import __startup__
__startup__.init()

# AP's client and game code use the legacy socket .open and .closed properties.
import websockets.legacy.client
websockets.connect = websockets.legacy.client.connect

# Path Client to Windows AppData
os.chdir(STATE)
os.environ['TCL_LIBRARY'] = str(archipelago / 'share/tcl8.6')
os.environ['TK_LIBRARY'] = str(archipelago / 'share/tk8.6')
import Utils
Utils.local_path = lambda *parts: str(archipelago.joinpath(*parts))
Utils.user_path = lambda *parts: str(STATE.joinpath(*parts))
if os.environ.get('GOLDENEYE_DESKTOP'):
    sys.stdout = open(STATE / 'launcher.log', 'a', buffering=1, encoding='utf-8')
    sys.stderr = sys.stdout

# Register the installed world
import worlds
worlds.__path__.append(str(archipelago / 'custom_worlds/goldeneye.apworld'))
from worlds import goldeneye
worlds.network_data_package['games']['GoldenEye 007'] = goldeneye.GoldeneyeWorld.get_data_package_data()


import asyncio
import colorama
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import hashlib
import logging
import math
from queue import SimpleQueue
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox
from worlds.Files import AutoPatchRegister
from CommonClient import CommonContext, get_base_parser, server_loop

GoldeneyeClient = goldeneye.GoldeneyeClient
GoldeneyeWorld = goldeneye.GoldeneyeWorld
logger = logging.getLogger('Client')


# Read and write 1964 memory.
class RequestFailedError(RuntimeError):
    pass

kernel = ctypes.WinDLL('kernel32', use_last_error=True)
ntdll = ctypes.WinDLL('ntdll')
HANDLE = wintypes.HANDLE
SIZE = ctypes.c_size_t
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.OpenProcess.restype = HANDLE
kernel.CloseHandle.argtypes = [HANDLE]
kernel.ReadProcessMemory.argtypes = [HANDLE, ctypes.c_void_p, ctypes.c_void_p, SIZE, ctypes.POINTER(SIZE)]
kernel.WriteProcessMemory.argtypes = kernel.ReadProcessMemory.argtypes
kernel.VirtualQueryEx.argtypes = [HANDLE, ctypes.c_void_p, ctypes.c_void_p, SIZE]
kernel.VirtualQueryEx.restype = SIZE
for name in ('NtSuspendProcess', 'NtResumeProcess'):
    getattr(ntdll, name).argtypes = [HANDLE]
    getattr(ntdll, name).restype = wintypes.LONG

class MemoryRegion(ctypes.Structure):
    _fields_ = [('base', ctypes.c_void_p), ('allocation', ctypes.c_void_p),
                ('allocation_protect', wintypes.DWORD), ('partition', wintypes.WORD),
                ('size', SIZE), ('state', wintypes.DWORD), ('protect', wintypes.DWORD),
                ('kind', wintypes.DWORD)]

class Memory:
    def __init__(self, pid, rom_path):
        # Open the emulator launched for this game.
        self.handle = kernel.OpenProcess(0x0800 | 0x0400 | 0x0008 | 0x0010 | 0x0020, False, pid)
        if not self.handle:
            raise RequestFailedError(str(ctypes.WinError(ctypes.get_last_error())))
        self.rom = Path(rom_path).read_bytes()
        self.ram_base = 0x20000000
        self.rom_base = None
        self.tracker = None
        self.screen = None

    def close(self):
        kernel.CloseHandle(self.handle)

    def ram_ready(self):
        # 1964 maps its ROM before committing Expansion Pak memory on a cold boot.
        region = MemoryRegion()
        kernel.VirtualQueryEx(self.handle, self.ram_base + 0x7FFFFC,
                              ctypes.byref(region), ctypes.sizeof(region))
        return region.state == 0x1000 and not region.protect & 0x101

    def raw_read(self, address, size):
        data = ctypes.create_string_buffer(size)
        transferred = SIZE()
        if not kernel.ReadProcessMemory(self.handle, address, data, size, ctypes.byref(transferred)) or transferred.value != size:
            raise RequestFailedError(f'1964 Memory is Unavailable at {address:#x}. Load the AP ROM and Keep 1964 Open.')
        return data.raw

    @contextmanager
    def paused(self):
        # Freeze all emulator threads until this synchronous transaction finishes.
        if ntdll.NtSuspendProcess(self.handle) != 0:
            raise RequestFailedError('Could Not Pause 1964, Rerun the Game and Try Again.')
        try:
            yield
        finally:
            if ntdll.NtResumeProcess(self.handle) != 0:
                raise RequestFailedError('Could Not Resume 1964.')

    def find_rom(self):
        # Find the live ROM by its header, then verify its AP tables and identity.
        header = b''.join(self.rom[index:index+4][::-1] for index in range(0,64,4))
        address = 0
        region = MemoryRegion()
        while address < 0x80000000:
            if not kernel.VirtualQueryEx(self.handle, address, ctypes.byref(region), ctypes.sizeof(region)):
                break
            base = region.base or 0
            if region.state == 0x1000 and not region.protect & 0x101 and region.size >= len(self.rom):
                if self.raw_read(base,64) == header:
                    # 1964 applies built-in speed/firing patches to game code.
                    # Match the AP player identity and tables, then validate hooks in the client.
                    start = 0xBFE800
                    actual = self.raw_read(base+start,0x1400)
                    expected = b''.join(self.rom[index:index+4][::-1]
                                        for index in range(start,start+0x1400,4))
                    if actual == expected:
                        self.rom_base = base
                        return True
            address = base + region.size
        return False

    def read_field(self, address, size, domain):
        # Reverse native 32-bit words
        limit = len(self.rom) if domain == 'ROM' else 0x800000
        if domain not in ('ROM','RDRAM') or address < 0 or address + size > limit:
            raise RequestFailedError('Read is Outside the N64 Memory Domain.')
        base = self.rom_base if domain == 'ROM' else self.ram_base
        start = address & ~3
        end = (address + size + 3) & ~3
        raw = self.raw_read(base + start, end - start)
        data = b''.join(raw[index:index+4][::-1] for index in range(0,len(raw),4))
        return data[address-start:address-start+size]

    def write_field(self, address, data, domain):
        if domain != 'RDRAM' or address < 0 or address + len(data) > 0x800000:
            raise RequestFailedError('Writes Must Stay Inside RDRAM.')
        # Preserve adjacent bytes when the game requests a byte or half-word.
        start = address & ~3
        end = (address + len(data) + 3) & ~3
        merged = bytearray(self.read_field(start,end-start,domain))
        merged[address-start:address-start+len(data)] = data
        raw = b''.join(merged[index:index+4][::-1] for index in range(0,len(merged),4))
        transferred = SIZE()
        if not kernel.WriteProcessMemory(self.handle,self.ram_base+start,bytes(raw),len(raw),ctypes.byref(transferred)) or transferred.value != len(raw):
            raise RequestFailedError('1964 Memory Write Failed.')

async def read(memory, fields):
    with memory.paused():
        values = [memory.read_field(*field) for field in fields]
        for field, value in zip(fields, values):
            if field == (0x2A8C0, 4, 'RDRAM'):
                memory.screen = int.from_bytes(value, 'big')
        return values

async def guarded_write(memory, writes, guards):
    # Compare guards and commit
    with memory.paused():
        for address, expected, domain in guards:
            if memory.read_field(address,len(expected),domain) != bytes(expected):
                return False
        for address, data, domain in writes:
            memory.write_field(address,bytes(data),domain)
    return True

async def write(memory, writes):
    return await guarded_write(memory,writes,[])

async def send_requests(memory, requests):
    for request in requests:
        if 'missions' in request:
            memory.tracker = request
    return [{} for request in requests]


# Existing emulator and ROM paths.
ROM_MD5 = '70c525880240c1e838b8b1be35666c3b'


def player_configuration(force=False, emulator=None):
    config_path = STATE / 'settings.json'
    # Later launches reuse the saved choices.
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    if not force and 'rom' in config and Path(config['rom']).is_file() and Path(config['emulator']).is_file():
        return config
    root = tk.Tk()
    root.withdraw()
    # Choose the original installation and clean ROM; neither is copied.
    executable = str(emulator) if emulator else filedialog.askopenfilename(
        parent=root, title='First Launch: Choose your 1964.Exe', filetypes=[('1964 emulator', '1964.exe')])
    if not executable:
        root.destroy()
        return None
    while True:
        rom = filedialog.askopenfilename(parent=root, title='First Launch: Choose a Clean GoldenEye USA ROM',
                                        filetypes=[('GoldenEye USA ROM', '*.z64')])
        if not rom:
            root.destroy()
            return None
        if hashlib.md5(Path(rom).read_bytes()).hexdigest() == ROM_MD5:
            break
        messagebox.showerror('Choose a Clean ROM', 'Select the Original GoldenEye 007 USA .z64 ROM', parent=root)
    config.update(emulator=str(Path(executable).resolve()), rom=str(Path(rom).resolve()))
    config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
    root.destroy()
    return config


# Draw the client and the click-through mission tracker.
class ClientWindow(logging.Handler):
    def __init__(self, root, context, address):
        super().__init__()
        # Send normal AP commands through its existing command processor.
        self.command = context.command_processor(context)
        self.context = context
        self.messages = SimpleQueue()
        self.window = tk.Toplevel(root)
        self.window.title('GoldenEye 1964')
        self.window.geometry('640x400')
        self.window.protocol('WM_DELETE_WINDOW', context.exit_event.set)
        connection = tk.Frame(self.window)
        connection.pack(fill='x', padx=8, pady=8)
        self.address = tk.Entry(connection)
        self.address.insert(0, address or '')
        self.address.pack(side='left', fill='x', expand=True)
        tk.Button(connection, text='Connect', command=self.connect).pack(side='left', padx=(8, 0))
        messages = tk.Frame(self.window)
        messages.pack(fill='both', expand=True, padx=8)
        self.output = tk.Text(messages, wrap='word', state='disabled')
        scroll = tk.Scrollbar(messages, command=self.output.yview)
        self.output.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.output.pack(fill='both', expand=True)
        self.entry = tk.Entry(self.window)
        self.entry.pack(fill='x', padx=8, pady=8)
        self.entry.bind('<Return>', self.send)
        for name in ('Client', 'FileLog'):
            logging.getLogger(name).addHandler(self)

    def connect(self):
        self.command('/connect ' + self.address.get().strip())

    def send(self, event):
        if self.context.input_requests:
            self.context.input_requests -= 1
            self.context.input_queue.put_nowait(self.entry.get())
        else:
            self.command(self.entry.get())
        self.entry.delete(0, 'end')

    def emit(self, record):
        self.messages.put(self.format(record))

    def update(self):
        # Display queued logs on the same thread that runs Tk and the game loop.
        self.output.configure(state='normal')
        while not self.messages.empty():
            self.output.insert('end', self.messages.get() + '\n')
            self.output.see('end')
        self.output.configure(state='disabled')

    def close(self):
        for name in ('Client', 'FileLog'):
            logging.getLogger(name).removeHandler(self)
        super().close()

user = ctypes.WinDLL('user32', use_last_error=True)
user.GetForegroundWindow.restype = wintypes.HWND
user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]

SHORT_NAMES = {'Goldeneye Operations Manual': 'GE Op Manual', 'Key Analyzer Case': 'Key Analyzer',
               'Computer Room Keycard': 'Computer Key', 'Security Room Keycard': 'Security Key',
               'Interrogation Room Key': 'Room Key', 'I/O Circuit Board': 'I/O Board',
               'CPU Circuit Board': 'CPU Board', 'RSP Circuit Board': 'RSP Board',
               'RDP Circuit Board': 'RDP Board', 'Keycard Level 1': 'Keycard L1',
               'Keycard Level 2': 'Keycard L2', 'Keycard Level 3': 'Keycard L3'}


class Tracker:
    def __init__(self, pid):
        # Transparent text floats over the game without taking input or focus.
        self.pid = pid
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title('GoldenEye Item Tracker')
        self.root.overrideredirect(True)
        self.root.attributes('-transparentcolor', '#010203')
        self.canvas = tk.Canvas(self.root, bg='#010203', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.root.update_idletasks()
        self.handle = self.root.wm_frame()
        self.handle = int(self.handle, 0)
        style = user.GetWindowLongW(self.handle, -20)
        user.SetWindowLongW(self.handle, -20, style | 0x20 | 0x80 | 0x80000 | 0x8000000)
        self.previous = None

    def update(self, screen, snapshot):
        window = user.GetForegroundWindow()
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(pid))
        # Show the active game's mission menu, using the current AP snapshot.
        if screen != 7 or not snapshot or not snapshot['enabled'] or pid.value != self.pid:
            self.root.withdraw()
            self.previous = None
            self.root.update()
            return
        rectangle = wintypes.RECT()
        origin = wintypes.POINT()
        user.GetClientRect(window, ctypes.byref(rectangle))
        user.ClientToScreen(window, ctypes.byref(origin))
        width = rectangle.right
        height = rectangle.bottom - 42  # 1964's toolbar and status bar.
        layout = (width, height, str(snapshot))
        self.root.geometry(f'{width}x{height}+{origin.x}+{origin.y + 20}')
        if layout != self.previous:
            self.draw(width, height, snapshot)
            self.previous = layout
        self.root.deiconify()
        user.SetWindowPos(self.handle, -1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)  # Topmost, no focus.
        self.root.update()

    def draw(self, width, height, snapshot):
        # Match the original five-column, four-row tracker layout and ownership colors.
        self.canvas.delete('all')
        font_size = width / 105
        for mission in snapshot['missions']:
            items = mission['items']
            if not items:
                continue
            columns = 2 if len(items) > 5 else 1
            rows = math.ceil(len(items) / columns)
            for item in items:
                name = SHORT_NAMES.get(item['name'], item['name'])
                font_size = min(font_size, width * .14 / columns / (len(name) * .6), height * .12 / (rows * 1.25))
        font_size = max(5, int(font_size))
        left_edges = (.10, .26, .42, .58, .735)
        top_edges = (.13, .34, .55, .76)
        for index, mission in enumerate(snapshot['missions']):
            items = mission['items']
            columns = 2 if len(items) > 5 else 1
            rows = math.ceil(len(items) / columns) if items else 1
            for item_index, item in enumerate(items):
                x = width * (left_edges[index % 5] + .145 / columns * (item_index // rows))
                y = height * top_edges[index // 5] + item_index % rows * font_size * 1.25
                name = SHORT_NAMES.get(item['name'], item['name'])
                font = ('Arial', -font_size, 'bold' if item['owned'] else 'normal')
                self.canvas.create_text(x + 1, y + 1, text=name, font=font, fill='black', anchor='nw')
                self.canvas.create_text(x, y, text=name, font=font,
                                        fill='#00ff00' if item['owned'] else '#909090', anchor='nw')

    def close(self):
        self.root.destroy()


# 7. Apply the verified 1964 ROM changes.
def patch_for_1964(rom, changes):
    # A patch generated by this candidate already contains the native runtime.
    if rom[0xBF8000:0xBF8008] == b'GE1964v1':
        return rom
    # Validate every native-code precondition before changing any bytes.
    for change in changes:
        offset = change['offset']
        before = bytes.fromhex(change['before'])
        if rom[offset:offset + len(before)] != before:
            raise ValueError('This Patch Uses a Different ROM Build. Generate It With the Current Main or 1964 World.')
    # Replace the known code, padding and header-checksum ranges.
    patched = bytearray(rom)
    for change in changes:
        offset = change['offset']
        after = bytes.fromhex(change['after'])
        patched[offset:offset + len(after)] = after
    return bytes(patched)


# 8. Connect the existing game client to the memory bridge.
class Context1964(CommonContext):
    game = 'GoldenEye 007'
    items_handling = 0b111
    want_slot_data = True

    def __init__(self, server, password, memory):
        super().__init__(server,password)
        self.memory = memory
        # The installed game client uses this name for its memory connection.
        self.bizhawk_ctx = memory
        self.previous_menu_screen = None
        self.client_handler = GoldeneyeClient()
        self.slot_data = None
        self.server_seed_name = None
        self.ready = False

    async def server_auth(self, password_requested=False):
        if not self.ready:
            return
        await self.client_handler.set_auth(self)
        if self.auth is None:
            await self.get_username()
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.send_connect()

    def on_package(self, cmd, args):
        if cmd == 'RoomInfo':
            self.server_seed_name = args['seed_name']
        if cmd == 'Connected':
            self.slot_data = args.get('slot_data')
        self.client_handler.on_package(self,cmd,args)

async def watch(ctx, emulator, tracker, window):
    # Wait for the launched emulator to load the exact player ROM.
    while not ctx.exit_event.is_set() and emulator.poll() is None:
        if not ctx.ready:
            if ctx.memory.find_rom() and ctx.memory.ram_ready():
                marker=(await read(ctx.memory,[(0xBF8000,8,'ROM')]))[0]
                if marker!=b'GE1964v1':
                    raise RuntimeError('The Loaded ROM is Missing the 1964 Runtime Patch. Open your .apge With 1964GE_AP.Cmd Again.')
                if not await ctx.client_handler.validate_rom(ctx):
                    raise RuntimeError('The ROM is Incompatible With the Installed GoldenEye Apworld.')
                ctx.ready = True
                logger.info('Connected to 1964')
                if ctx.server:
                    await ctx.server_auth()
        else:
            # Keep the native debrief pages, then return to the AP mission map.
            screen_bytes = (await read(ctx.memory, [(0x2A8C0, 4, 'RDRAM')]))[0]
            screen = int.from_bytes(screen_bytes, 'big')
            if ctx.previous_menu_screen in (12, 13) and screen not in (7, 12, 13):
                await guarded_write(ctx.memory, [(0x2A8C0, (7).to_bytes(4, 'big'), 'RDRAM')],
                                    [(0x2A8C0, screen_bytes, 'RDRAM')])
            else:
                ctx.previous_menu_screen = screen
                await ctx.client_handler.game_watcher(ctx)
        tracker.update(ctx.memory.screen, ctx.memory.tracker)
        if window:
            window.update()
        await asyncio.sleep(0.05)
    ctx.exit_event.set()


def launch(*launch_args):
    parser = get_base_parser()
    parser.add_argument('patch_file',nargs='?')
    parser.add_argument('--emulator', type=Path)
    parser.add_argument('--configure', action='store_true', help='Error Occurred: Choose the Emulator and Vanilla ROM Again')
    args = parser.parse_args(launch_args)
    config = player_configuration(args.configure, args.emulator)
    if config is None:
        return
    GoldeneyeWorld.settings.rom_file = config['rom']
    if not args.patch_file:
        root = tk.Tk()
        root.withdraw()
        args.patch_file = filedialog.askopenfilename(title='Choose Your GoldenEye Room Patch',filetypes=[('GoldenEye patch','*.apge')])
        root.destroy()
        if not args.patch_file:
            return
    # Generate one patched ROM in AppData and use the original emulator.
    patch_file = (START_DIRECTORY / args.patch_file).resolve()
    patch = AutoPatchRegister.get_handler(str(patch_file))(str(patch_file))
    rom = STATE / 'play.z64'
    patch.patch(str(rom))
    rom_data = bytearray(patch_for_1964(rom.read_bytes(), NATIVE_PATCH))
    # Double guard hit accumulation, then update the ROM checksum.
    rom_data[0x6200C:0x62010] = bytes.fromhex('46021080')
    rom_data[0x10:0x18] = bytes.fromhex('e3b6fadf26fb8ab2')
    rom.write_bytes(rom_data)
    executable = Path(config['emulator'])
    # 1964's -g option reads this saved folder; -r changes its ROM list.
    config_path = executable.with_name('1964.cfg')
    lines = config_path.read_text().splitlines()
    for index, line in enumerate(lines):
        if line.startswith('LastROMDirectory '):
            lines[index] = 'LastROMDirectory ' + str(STATE)
    config_path.write_text('\n'.join(lines) + '\n')
    emulator = subprocess.Popen([str(executable), '-g', rom.name], cwd=executable.parent)
    server = args.connect or patch.server

    async def main():
        memory = Memory(emulator.pid,rom)
        ctx = Context1964(server,args.password,memory)
        ctx.server_task = asyncio.create_task(server_loop(ctx),name='ServerLoop')
        if not os.environ.get("GOLDENEYE_DESKTOP"):
            ctx.run_cli()
        tracker = Tracker(emulator.pid)
        window = None if args.nogui else ClientWindow(tracker.root, ctx, server)
        try:
            await watch(ctx, emulator, tracker, window)
        finally:
            ctx.exit_event.set()
            if window:
                window.close()
            tracker.close()
            memory.close()
            await ctx.shutdown()

    Utils.init_logging('Goldeneye1964Client',exception_logger='Client')
    colorama.just_fix_windows_console()
    asyncio.run(main())


# AI Generated patch for 1964, adapted from the bizhawk patches.
NATIVE_PATCH = [
    {
        "offset": 0x10,
        "before": (
            "fbba9e5f5ac06784"
        ),
        "after": (
            "fbba9adf44b92bad"
        ),
    },
    {
        "offset": 0xbf4000,
        "before": "ff" * 16392,
        "after": (
            "3c02800727bdffa83442a0b0afb100348c510000afb200383c028000008090253c04007f022210213484d6010044102b"
            "afb7004cafbf0054afbe0050afb60048afb50044afb40040afb3003cafb000301440001100c0b825aee00008aee0002c"
            "aef2001c000010258fbf00548fbe00508fb7004c8fb600488fb500448fb400408fb3003c8fb200388fb100348fb00030"
            "03e0000827bd0058322200035440ffefaee000083c0280023442a8c08c4400002402000b5482ffe9aee000083c028003"
            "8c446494240200045482ffe4aee000088e2200d85440ffe1aee000088e2201c85440ffdeaee000083c02800434428370"
            "8c4200005440ffd9aee000083c027f093442a4640040f80900000000afa200108fa30010240200015462ffd0aee00008"
            "8ef5000056b1ffcdaee000088ea411e48ee200045482ffc9aee000088ea811e48e2911e08e2a11e82542ffff2c420080"
            "5040ffc2aee000080503ffc0aee00008000a1080004a1021000210803c048080008220230088202b5480ffb8aee00008"
            "310400035480ffb5aee000081120003a0128202b1480ffb0010210210122202b1080ffad01282023240500140085001b"
            "00a001f4000020101480ffa70120202500006025240e0014240f0002008030258c84000c0088282b14a0ff9f0082282b"
            "10a0ff9d0088282300ae001b01c001f40000281054a0ff99aee000088c85001054a6ff96aee000088ca6000014cf0014"
            "3c06007f8cab00043c0580000165682134c6fff901a6682b51a0ff8caee00008316d000355a0ff89aee000088d6b0004"
            "24c6ff880165282100a6282b50a0ff83aee00008316b00035560ff80aee0000811240005258c0001554cffd900803025"
            "1000ff7aaee00008324210001440ff7632560f008ee20030244200018ef0001caee2003016c00054aef2001c24020001"
            "aee2002c3c028004344283748c420000afa200143242080014400003241effff0012f28233de000132440c0024020c00"
            "508200010000f0258ef4000800108027168001180212802432100c001200ff5e24020f0024020001aee2000824020015"
            "aee200208ee20018aee0002414400010aefe00288ee2000c1440000e3c127f083c107f053610d434000028250200f809"
            "0000202524040001000028250200f809004088250002220000911025aee200183c127f083652d038aee000148ef10000"
            "0240f8093c167f06265e00d0afa20014000080252652027036d6942c8fa200140202102a1440001d26e400408ee20014"
            "0282282a54a000e48c8600008ee400100082202a548000048ee400102444ffffaee400108ee4001004820001aee00010"
            "5040ff2924020f008ee400100004104000441021000210c002e210218c42004010000004aee200188ee2002c5440ffae"
            "3c0280041000ff1c24020f0003c0f80902002025020020250240f8090040a825004098252442ffc22c42001610400095"
            "8eea000c2402004916620095026028252a65002138b500011555009cafa5001802c0f809026020252404000312640009"
            "2664ffe62c840004548000072444ffff8fa5001854a0009702602825584000978fb500102444ffff2c84001d1080008b"
            "2624113000021080008210218c4200008e24087016640003000000008e24089c004410218e240c181664000300000000"
            "8e240c44004410211840007c02602825000050253c027f08afaa001cafa500183442d3400040f8090200202500403825"
            "26e900408ee200148fa500188faa001c01202025000058250162602a558000758c8c0000240400a01044000c24440001"
            "aee400140002204000822021000420c002e42021ac850040ac900044ac930048ac80004cac870050ac8a005456a0ff8f"
            "261000018e2b11e00000502501601025240c000310400025000000008e2411e80144202a10800021000000008c440000"
            "548c001c8c42000c8c440004566400198c42000c8c4d00088eef0014000d2a0000b328250120702500002025008fc02a"
            "570000598dd80000240400a011e4000c25e40001aee40014000f2040008f2021000420c002e42021ac850040ac900044"
            "ac930048ac8d004cac870050ac8000548c42000c5562ffdb254a00018e2211ec5040ff62261000013c027f05afa7001c"
            "afa900183c0500103442e0b40040f809026020258fa90018104000248fa7001c00132a008ee2001400b3282502a2202a"
            "548000398d240000240400a01044001b24440001aee400140002204000822021000420c002e42021ac850040ac900044"
            "ac930048ac93004cac8700501000000fac8000541660ff6f2a6500210000282512a000073c0200018ea4000024420001"
            "1082000824020002508200018ea50004241500011155ff883c027f081000ff332610000192a500053c0200011000fff8"
            "00a228251000ff7e0000a8251000ff7c026028251185ff990000000051400008256b00018c8c001451800005256b0001"
            "8c8c001010ecff9100000000256b00011000ff7d2484001810b8ffb525ce00181000ffa22484000110a4ffe425290018"
            "1000ffc226b500018ee5001814c50003248400181000ff2faef400101000ff142694000132020200104000063c147f08"
            "8ee2000caee0001038420001aee2000caee000183694d0380280f809aee00014afa2001826820270afa2001c3c027f06"
            "3442942c00009025afa200208fa200180242102a1440001a3c027f088ee2001426e50040000020250082302a54c000e3"
            "8ca700008ee400100082202a548000048ee400102444ffffaee400108ee4001004820001aee00010104000e900000000"
            "8ee500100005204000852021000420c002e420218c840040100000d4aee400183442d1080040f8090240202500409825"
            "8fa2001c0040f809024020250040a0252442ffc22c420016104000988eeb000c240200491682009802802825166000a7"
            "240500498fb300101573009eafa500248fa200200040f80902802025240400031284000a8fa500242684ffe62c840004"
            "148000072444ffff2a8400211480001700005825584000163c027f082444ffff2c84001d1080008b26a4113000021080"
            "008210218c4200008ea4087016840003000000008ea4089c004410218ea40c1816840003000000008ea40c4400441021"
            "5840ffae26520001000058253c027f08afab0028afa500243442d3400040f8090240202526ea00408eec00148fa50024"
            "8fab0028004048250000202501401025008c682a55a000748c4d0000240200a01182000c25820001aee20014000c1040"
            "004c1021000210c002e21021ac450040ac520044ac540048ac40004cac490050ac4b00545660ff8d265200018eae11e0"
            "0000582501c020252418000310800025000000008ea211e80162102a10400021000000008c8200005458001c8c84000c"
            "8c820004568200198c84000c8c8f00088ee20014000f2a0000b4282501406825000060250182c82a572000588db90000"
            "240c00a0104c000c244c0001aeec00140002604001821021000210c002e21021ac450040ac520044ac540048ac4f004c"
            "ac490050ac4000548c84000c55c4ffdb256b00018ea211ec5040ff60265200013c027f05afa90028afaa00243c050010"
            "3442e0b40040f809028020258faa0024104000248fa9002800142a008ee4001400b428250264102a544000388d420000"
            "240200a01082001b24820001aee200140004104000441021000210c002e21021ac450040ac520044ac540048ac54004c"
            "ac4900501000000fac400054168000130280282500002825126000073c0200018e640000244200011082000824020002"
            "508200018e650004241300011173ff883c027f081000ff3126520001926500053c0200011000fff800a228252a880021"
            "1000ff593913000111a5ff9a0000000051600008248400018c4d001451a00005248400018c4d0010112dff9200000000"
            "248400011000ff7e2442001810b9ffb625ad00181000ffa3258c000110a2ffe5254a00181000ffc3267300018ee60018"
            "14e6000d24a50018aee4001053c000180040f0258ee4002857c40004aefe002832040c00508000628ee4002024040015"
            "10000067aee400201000ff0b2484000153c0000c240200158ee4002813c4005532040c00aefe002824020015aee20020"
            "52c00069000010251000fe12aee0002424020015aee20020aee0002803c0102552c000628ee40024aee0002432100100"
            "5200fd2524020f001040fd2324020f008ef300100013804002131021000210c002e210218c4400545480fd1b24020f00"
            "8c5200483c027f063442942c0040f8090240202524040003124400092644ffe62c840004148000072444ffff2a440021"
            "548000170213802158400015021380212444ffff2c84001d1080fdea2624113000021080008210218c4200008e240870"
            "14920003000000008e24089c004410218e240c1816440003000000008e240c44004410215840fcf824020f0002138021"
            "001080c002f080218e0500483c117f053631d4e0000030250220f809000020258e05004c000030250220f80924040001"
            "8e020048aee200388e02004caee00008aee2003c8ee20034244200011000fdc5aee200345480ffad240200158ee40020"
            "8fa300140083202358800003240400071000ffafaee400201040ffa5aee400208ee4001003c4f02103c2f02103c2001a"
            "004001f40000f010001e2040009e2021000420c002e420218c840040aefe00101000ff9faee400188ee400248fa30014"
            "0064a821aef500242ab500b452a0ff9baee000081000ff9a321001008ca2000827bdfe68afb10174afbf0194afbe0190"
            "afb7018cafb60188afb50184afb40180afb3017cafb20178afb001701040018f008088258ca300003c0280003c04007f"
            "006210213484d6010044102b1040018700a0802530620003544001858fbf01943c0280023442a8c08c4400002402000b"
            "5482017f8fbf01943c0280038c446494240200045482017a8fbf01948c6200d8544001778fbf01948c6201c814400174"
            "8fbf01943c028004344283708c420000544001708fbe01903c027f093442a4640040f809000000002403000114430168"
            "8fbf01943c0280073442a0b08c4300008e020000546201638fbe01903c127000264245140040f8092652452424430008"
            "24420078afa301680240f809afa20164004018253c0280038c42642c5440008a246300202463000d3c0280048c440eb8"
            "3c127f0a8c82088c8c8408903652cd98004410210002284000a2282100a31821246200062463005eafa3015c02202025"
            "0240f809afa2016027a3015cafa3001027a6016027a5016800402025265201b40240f80927a70164004020258fa60168"
            "8fa301608e02000c24c6000724630005104000703c05b0bf34a5e0208fa20164afa300f0afa60150000018252407000a"
            "2408005f00a3302180c6000050c0000827a5003010c7000527a9003001234821246300011468fff7a126000027a50030"
            "00a3182100021400a0600000000214033c0380048c650eb08c630eacafa2001c3c02d4c52406000b34428affafa60028"
            "afa20018240600f03c027f0aafa60020afa50010afa00024afa3001427a7003027a600f03442dabc0040f80927a50150"
            "004088258e020014544000312402000b8fa401608fa501682484002124a5000e8fa30164afa50150afa400f03c06b0c0"
            "2405000a2407005f00c220218084e0405080000827a400301085000527a8003001024021244200011447fff7a1040000"
            "27a4003000821021a04000003c0280048c440eb08c450eac2402000bafa20028240200f0afa200200003140000021403"
            "afa2001c3c02b8b83442b8ffafa200183c027f0aafa50014afa40010afa000240220202527a7003027a600f03442dabc"
            "0040f80927a50150004088252402000bafa201582416ffff2414ffff241500028e0200145440000d8e1700103c02b0bf"
            "100000963442e0702402000b0062001a004001f400001010006218231000ff722463fffe1000ff9134a5e00002d7b821"
            "06e0007902e2102a104000778fb301608fa4016812d400d38fb2016416c000c48fa201582484000526730021afa40150"
            "afb300f0000010253c05b0c02404000a2406005f00a218218063e0505060000827a300301064000527a7003000e23821"
            "244200011446fff7a0e3000027a3003000621021a04000003c0280048c430eb02404000b8c420eac00129400afa40028"
            "240400f0afa40020001294032404ffffafa200143c027f0aafb2001cafa4001827a5015002202025afa00024afa30010"
            "27a700303442dabc0040f80927a600f0004088250017104000571021000210c08fa401688fb20164020210218c450050"
            "2484000e2652fffc2417ffff27be0158afa4015410a00038afb30150000010252406000a2407005f00a2182180630000"
            "5060000827a300301066000527a800f001024021244200011447fff7a103000027a3003000621021a04000c013c0000c"
            "27a700f03c0280048c470eb08c420eac00603025afa200103c027f0a27a500f03442eb640040f8090244202327a70030"
            "3c0280048c430eb08c420eac2404000b00129400afa40028afa20014240400f0001294033c027f0aafa40020afa00024"
            "02202025afb2001cafb70018afa3001027a601503442dabc0040f80927a5015413c00005004088258fa2015000531023"
            "2442000bafc2000026d6000116d5ff758e0200141040ff763c02b0bf8e0300100003104000431021000210c002028021"
            "8e020054144000553c02b0bf8e02004c1040ff6b3c02b0bf3442e0b08fa301608fa401588fa501682463003100641821"
            "24a500078fa40164afa300f0afa50150000018252406000a2407005f0043282180a5000050a0000827a2003010a60005"
            "27a8003001034021246300011467fff7a105000027a2003000431821a06000003c0280048c430eb08c450eac2402000b"
            "afa20028240200f0afa200200004140000021403afa2001c3c02d4c534428aff3c107f0a02202025afa50014afa30010"
            "3610dabc27a7003027a600f027a50150afa000240200f809afa200182610f4340200f80900402025004088258fbf0194"
            "8fbe01908fb7018c8fb601888fb501848fb401808fb3017c8fb201788fb00170022010258fb1017403e0000827bd0198"
            "24420023005398210017104000571021000210c0020210213c178f9c8c4500502484000e2652fffc36f79fff1000ff68"
            "0000f0251000fff4267300151000ffaf3442e09000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "00000000000000000000000000000000000000000000000000000000000000003c0280023442a8c08c4300002402000b"
            "14620247000000003c0280003c03007f008210213463d5810043102b1040024000000000308200031440023d00000000"
            "8c8811e48c8211e82443ffff2c630080106002370000000005010235000000000002188000621821000318803c028080"
            "004310230048102b1440022d00000000310800031500022a000000008ca2000027bdffd8afbe0024afb70020afb6001c"
            "afb50018afb40014afb30010afb2000cafb1000814400016afb0000424020001aca200002402ffffaca200043c028007"
            "3442f020ac400000ac4001a08c4301f824630001ac4301f8ac4001fcac400200ac400204ac4001e0ac4001e4ac4001ec"
            "a04001eba04001e9a04001eaac4001f08ca2000c144000103c0280023c0280038c436494240200041462000b3c028002"
            "3c02800734429a208c4300002c63003c546000053c02800224030001ac435600aca3000c3c0280023c0380073442a8f8"
            "3463f2048c4600008c62000054400005000212028c63fffc506000093c02800700021202304200ff104600043c028007"
            "3442f200ac400000ac4000043c0280073442f1c48c4600002cc2002150400001000030258ca3001024b8001c00661826"
            "3c0c80070003182b0300702500006825358cf150240f001c14cd00d0000d48c01060000424030020aca60010aca00014"
            "aca0001810c300042402ffff2402000100c210042442ffff8cac0014118200323c02800634429c383c0d007f3c0e01ff"
            "01805825241900013c12800035adff7d2413000835ceffff24140004245179e08c47000490430000306300ff50790003"
            "00f218211474001c00f21821006d182b5060001a2442003430ea000355400017244200348ce300105462001424420034"
            "8cf5000490e3008090ef0003306300ff31ef00ff15f30009000048252c6f002115e00003240f0058146f000503007825"
            "8ce9000800094b82312900010300782554ca00ad8de30000244200341451ffdc00000000acab00148c9811e08c8d11e4"
            "8c8f11e8248e11e0000f388000ef38210007388000ed3821000048250300102500003025240a0014240b0001240c0058"
            "152f00b4004d182b8c8308702402005810620004240900018c8911f0392900582d2900013c19807f24a200a800c98825"
            "241000013739ffcd8ca300180103182b546000b88c4b000810c0001e000000008cc2000c3c0380003c08007f00435021"
            "3508ffed0148502b8cc7001024cc000c8c8d11e01140001324cb001000e318210068182b1060000f0047182530630003"
            "1460000c0000000014c201430000000014c7014100000000ac8011e02402ffffacc20000acc00004acc00008ad800000"
            "ad6000001120000e3c0380072402ffffac800870ac820874ac80089cac8008a0ac8008b0ac8008b8ac8007f8ac800800"
            "ac822a44ac802a4cac8011f03c0380073462f2108c480000110000218ca2009c1440001f000000003c06007f24629c38"
            "3c09800034c6ff7d240a002d246416188c4300040069382100e6382b50e00120244200343067000354e0011d24420034"
            "9067000330e700ff54ea0119244200348c67000454e80116244200348c6700105447011324420034aca3009caca200a0"
            "9042000130420004aca200a48ca2009c1040010f8ca400a08c43001054640010aca0009c8c6400045482000daca0009c"
            "3c0480073484f20a906200019084000024070001308400ff304200fb148700020000302590a600a700461025a0620001"
            "8fbe00248fb700208fb6001c8fb500188fb400148fb300108fb2000c8fb100088fb0000403e0000827bd0028012d4823"
            "00094880000038250000502500e95821000b10c2004c102190420000316b0007304200ff016210073042000100e21004"
            "24e7000114effff5014250258dc20000544a000124030001adca000025ad00011000ff1925ce00040159800402a3b026"
            "02ceb0240190b82402d7b02516c0001200031e423063000155230010254a00018cb600182ec302585060000c254a0001"
            "26c30001aca3001800161840007618210003188000a31821ac6700a8ac6200acac6a00b001705825254a00011000ff38"
            "25ef00041460ff4c0047182b1060ff4a004d1823006a001b014001f4000018101460ff45000000008c430000146b0004"
            "000000008c430004506c0001004030258c42000c1302ff3c000000001000ff38252900018c4c0000316b001f25630006"
            "0003188000a318218c7200048d8a001000121e8205410079306300030159982b1660005d315400035470005925080001"
            "8c4c0008318c0040558000738c4300088dc300002412001424150002118f003a006d502b154000380067502b11400036"
            "006d50230152001b024001f400005010554000328c4300088c6a000c8c740000169500792473000c8c7700048c560004"
            "16f60075247400043c0c8007358cf1c08d920000240a0001016a500401525025ad8a00008e6a00003c0c80003c17007f"
            "014cf02136f7ffed03d7f02b8c720010247500108dd6000053c000158c430008024c60210197602b518000118c430008"
            "01526025318c00035580000d8c430008146a0053000000001472005100000000adc00000240affffac6a0000ae800000"
            "ac600008ae600000aea000008c43000834630040ac4300088c4300088c8a00a830630040546000122508000151400010"
            "250800018c4300048c63001c546a000c250800013c0a8007354af1c08d4c00002403000101631804006c1825ad430000"
            "8c43000834630040ac430008250800011000fedd2442000c1280000600000000240c0001546cfffa250800011000ffa1"
            "8c4c00089193000324150008327300ff5675fff8240c00013c1380078e761df42ed7020112e0fff22675162012d4fff0"
            "00149880027598218e7300001153002e269400011000fff9000000005070ff8d8c4c00088c430008306300205060ffe0"
            "250800015540ffde250800015220ffdc250800013c0a8007354af1c08d4c00002403000101631804006c1825ad430000"
            "8c430008240affdf1000ffcf006a1824ae4a000cad5200105076ffaeadca00001000ffad240affff130affb3258c0001"
            "1000ff7601401825ace2000cac47001050cdfebeac8211e01000febd2402ffff1444fedb000000001000fef18ca2009c"
            "1000ff03aca0009c3c1302000253902412400005241200588d52001c5640ffb9240c000124120058a19200808d920008"
            "3c13fde73673ffff02539024ad9200088c4c0008358c00201000ffadac4c000803e00008000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            "000000000000000000000000000000004745313936347631"
        ),
    },
    {
        "offset": 0xbfb600,
        "before": (
            "27bdffe0afbf001c0c01feae000000003c088008ad00ff603c19700037399720240430000320f809240500041040001f"
            "000000003c088008ad02ff603c09b0c02529c00000405025244b20008d2c0000ad4c000025290004254a0004154bfffb"
            "00000000244d3000ad400000254a0004154dfffd000000008d0ca0b0ad0cff64ad6c00008d8c11e4ad0cff68ad6c0004"
            "00405025bd5900000000000fbd500000254a0010154bfffb000000008fbf001c03e0000827bd00203c0280082442a0b0"
            "8c4f000027bdffe83c197f003739626c032000080000000027bdffd8afbf0024afa40010afa50014afa60018afa7001c"
            "0c01fef2000000000040c825132000070000102500c0202500e0282527262000273900000320f809000000008fa40010"
            "8fa500148fa600188fa7001c0040102700c2302400e238248fbf002427bd002827bdfe40f7b400304480a000afbf003c"
            "3c197f0837391984032000080000000027bdffe0afbf001c0c01feea00000000afa200100c01fef2000000000040c825"
            "8fa2001013200005004020252725200027390d6c0320f809000000008fbf001c03e0000827bd00203c0280088c42a0b0"
            "27bdffa0afbf00343c197f083739a60c0320000800000000000010253c0880038d09a8c0240a000b152a000d00000000"
            "3c0880088d09a0b08d0aff641120000800000000152a0006000000008d2911e48d0aff68152a0002000000008d02ff60"
            "03e000080000000000000000000000003c0880028d0841a82409002b3c0a80031509000b000000008d483f7c8d493f80"
            "ad48436cad4943702408002f1488000a000000002404001d10000007000000003c0880042508cec03c098005252939c8"
            "ad48436cad494370248efffd27bdffe82dc1002eafbf00143c197f003739572003200008000000002408002f14a80007"
            "000000003c0880028d0841a82409002b1509000200000000240400c70004708027bdff4801c47023000e70803c197f05"
            "3739207c03200008"
        ) + "00" * 40,
        "after": (
            "27bdffe0afbf001c0c01feae000000003c088008ad00ff603c19700037399720240470000320f809240500041040001f"
            "000000003c088008ad02ff603c09b0bf3529400000405025244b40008d2c0000ad4c000025290004254a0004154bfffb"
            "00000000244d7000ad400000254a0004154dfffd000000008d0ca0b0ad0cff64ad6c00008d8c11e4ad0cff68ad6c0004"
            "00405025bd5900000000000fbd500000254a0010154bfffb000000008fbf001c03e0000827bd00203c0280082442a0b0"
            "8c4f000027bdffe83c197f003739626c032000080000000027bdffd8afbf0024afa40010afa50014afa60018afa7001c"
            "0c01ff0c000000000c01fef8000000000040c82513200009000010258fa600188fa7001c00c0202500e0282527264000"
            "273900000320f809000000008fa400108fa500148fa600188fa7001c0040102700c2302400e238248fbf002427bd0028"
            "27bdfe40f7b400304480a000afbf003c3c197f0837391984032000080000000027bdffe0afbf001c0c01fef000000000"
            "afa200100c01ff0c000000000c01fef8000000000040c8258fa2001013200005004020252725400027390d6c0320f809"
            "000000008fbf001c03e0000827bd00203c0280088c42a0b027bdffa0afbf00343c197f083739a60c0320000800000000"
            "000010253c0880038d09a8c0240a000b152a000d000000003c0880088d09a0b08d0aff641120000800000000152a0006"
            "000000008d2911e48d0aff68152a0002000000008d02ff6003e000080000000027bdffe8afbf00140c01fef800000000"
            "10400007000000003c0480088c84a0b024455000245920000320f809000000008fbf001403e0000827bd0018"
        ) + "00" * 148,
    },
    {
        "offset": 0xbfba00,
        "before": "00" * 352,
        "after": (
            "3c0880028d0841a82409002b3c0a80031509000b000000008d483f7c8d493f80ad48436cad4943702408002f1488000a"
            "000000002404001d10000007000000003c0880042508cec03c098005252939c8ad48436cad494370248efffd27bdffe8"
            "2dc1002eafbf00143c197f003739572003200008000000002408002f14a80007000000003c0880028d0841a82409002b"
            "1509000200000000240400c70004708027bdff4801c47023000e70803c197f053739207c03200008"
        ) + "00" * 168,
    },
    {
        "offset": 0x3ad90,
        "before": (
            "3739fa00"
        ),
        "after": (
            "3739fa00"
        ),
    },
    {
        "offset": 0xb64a8,
        "before": (
            "3739fad8"
        ),
        "after": (
            "3739fad8"
        ),
    },
    {
        "offset": 0xbf130,
        "before": (
            "3739fb60"
        ),
        "after": (
            "3739fb70"
        ),
    },
    {
        "offset": 0x3a244,
        "before": (
            "3739fc20"
        ),
        "after": (
            "3739fe00"
        ),
    },
    {
        "offset": 0x86ba0,
        "before": (
            "3739fc98"
        ),
        "after": (
            "3739fe78"
        ),
    },
]


if __name__ == '__main__':
    game = importlib.import_module('worlds.goldeneye.GoldeneyeClient')
    game.bizhawk = sys.modules[__name__]
    launch(*sys.argv[1:])
