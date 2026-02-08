import os
import shutil
import time
from pathlib import Path
from datetime import datetime

mount = "/home/daniel/mount/cdrom"
output = "./out"
root = Path(mount) / "Pictures"

def rip():
  os.system(f'mkdir -p {output}')
  
  ## Count files
  print("Scanning files...", end='', flush=True)
  total_files = 0
  for filePath in root.rglob('*'):
    if filePath.is_file() and 'index' not in filePath.name.lower():
      total_files += 1
  print(f" Found {total_files} files")
  
  if total_files == 0:
    return
  
  print("Copying files:")
  bar_length = 50
  current_file = 0
  
  ## Copy files
  for filePath in Path(root).rglob('*'):
    if not filePath.is_file() or 'index' in filePath.name.lower():
      continue
    current_file += 1
    
    modTime = datetime.fromtimestamp(os.path.getmtime(filePath))
    newName = f"{modTime.strftime('%Y%m%d_%H%M%S')}{filePath.suffix}"
    newPath = os.path.join(output, newName)
    
    counter = 1
    while os.path.exists(newPath):
      base = modTime.strftime('%Y%m%d_%H%M%S')
      newName = f"{base}_{counter}{filePath.suffix}"
      newPath = os.path.join(output, newName)
      counter += 1
    
    ## Copy
    shutil.copy2(filePath, newPath)
    
    ## Update progress bar
    progress = current_file / total_files
    filled_length = int(bar_length * progress)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    
    clear_line = ' ' * 80
    print(f"\r{clear_line}\r[{bar}] {current_file}/{total_files} ({progress*100:.1f}%)", end='', flush=True)
  
  print(clear_line)
  print(f"Copied {total_files} files to {output}")


def mountCd():
  drive = "/dev/cdrom"

  os.system(f'mkdir -p {mount}')

  os.system('sudo eject -t') ## Close drive

  time.sleep(1)

  with open("/proc/mounts", "r") as proc:
    if mount in proc.read():
      return True, "Already Mounted"
  
  try:
    os.system(f'sudo mount {drive} {mount}')
    if os.path.ismount(mount):
      print("Mounted")
  except:
    print("Failed to mount")

  return False, "Failed"

def unmount():
  print("Unmounting")
  os.system(f'sudo umount {mount}')

  with open("/proc/mounts", "r") as f:
    if mount not in f.read():
      os.system('sudo eject')
      print("CD ejected")
    else:
      print("Could not unmount")

def upload():
  print("Uploading to Immich...")
  os.system(f'immich upload -c 12 {output}')

  print("Removing uploaded...")
  os.system(f'rm -rf {output}/*')


unmount()
while True:
  input("Press Enter to continue...")
  mountCd()
  rip()
  upload()
  unmount()
  
