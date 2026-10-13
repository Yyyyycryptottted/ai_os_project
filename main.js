const { app, BrowserWindow, globalShortcut } = require('electron');
const { spawn } = require('child_process');
const path = require('path');

let win;
let pythonProcess;
function updateIslandVisibility() {
  const openWins = Array.from(document.querySelectorAll('.win')).filter(w => {
    return w.style.display === 'flex' && !w.classList.contains('close-anim');
  });
  if (openWins.length > 0) {
    document.body.classList.add('has-active-window');
  } else {
    document.body.classList.remove('has-active-window');
  }
}

const hide = id => {
  try {
    const w = document.getElementById('w-' + id);
    if (!w) return;
    w.classList.remove('open-anim');
    w.classList.add('close-anim');
    setTimeout(() => {
      if (w.classList.contains('close-anim')) w.style.display = 'none';
      updateIslandVisibility();
    }, 280);
    const rBtn = document.getElementById('r-' + id);
    if (rBtn) rBtn.classList.remove('open');
  } catch (e) { console.error(e); }
};

function openWindow(id) {
  try {
    id = String(id).replace('win-', ''); 
    const w = document.getElementById('w-' + id);
    if (!w) return;
    
    w.style.display = 'flex';
    void w.offsetWidth;
    
    w.classList.remove('close-anim');
    w.classList.add('open-anim');
    front(id);
    
    const rBtn = document.getElementById('r-' + id); 
    if (rBtn) rBtn.classList.add('open');
    
    updateIslandVisibility();
    
    if (id === 'mypc') { try { pcRender(); } catch (e) {} }
    if (id === 'settings' && !pg) { try { go('home'); } catch (e) {} }
  } catch (e) {
    console.error(e);
  }
}

function createWindow() {
  win = new BrowserWindow({
    width: 1920,
    height: 1080,
    fullscreen: true,
    frame: false,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      webviewTag: true // <--- THIS ALLOWS THE BUILT-IN BROWSER TO WORK
    }
  });

  win.loadFile('login.html');

  pythonProcess = spawn('python', ['-u', path.join(__dirname, 'brain.py')]);

  pythonProcess.stdout.on('data', (data) => {
    const message = data.toString();
    console.log("Python:", message);
    if (win) {
      win.webContents.send('ai-status', message);
    }
  });

  pythonProcess.stderr.on('data', (data) => {
    console.error("Python Error:", data.toString());
  });

  globalShortcut.register('CommandOrControl+R', () => {
    if (pythonProcess && pythonProcess.stdin) {
      pythonProcess.stdin.write('ACTIVATE\n');
    }
  });

  globalShortcut.register('CommandOrControl+F', () => {
    if (pythonProcess && pythonProcess.stdin) {
      pythonProcess.stdin.write('DEACTIVATE\n');
    }
  });
}

app.whenReady().then(createWindow);

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  if (pythonProcess) pythonProcess.kill();
});