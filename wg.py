import os
import shutil
import time
from pathlib import Path
from datetime import datetime

mount = "/home/daniel/mount/cdrom"
output = "./out"
root = "./Pictures"

def rip():
    os.system(f'mkdir -p {output}')
    
    ## First pass: count files
    print("Scanning files...", end='')
    total_files = 0
    for file_path in Path(mount).rglob(f'{root}/*'):
        if file_path.is_file() and 'index' not in file_path.name.lower():
            total_files += 1
    print(f" Found {total_files} files")
    
    if total_files == 0:
        return
    
    print("Copying files:")
    bar_length = 50
    current_file = 0
    
    ## Second pass: copy files
    for file_path in Path(mount).rglob(f'{root}/*'):
        if not file_path.is_file() or 'index' in file_path.name.lower():
            continue
        
        current_file += 1
        
        modTime = datetime.fromtimestamp(os.path.getmtime(file_path))
        newName = f"{modTime.strftime('%Y%m%d_%H%M%S')}{file_path.suffix}"
        newPath = os.path.join(output, newName)
        
        counter = 1
        while os.path.exists(newPath):
            base = modTime.strftime('%Y%m%d_%H%M%S')
            newName = f"{base}_{counter}{file_path.suffix}"
            newPath = os.path.join(output, newName)
            counter += 1
        
        shutil.copy2(file_path, newPath)
        
        ## Update progress bar
        progress = current_file / total_files
        filled_length = int(bar_length * progress)
        bar = '█' * filled_length + '░' * (bar_length - filled_length)

        print(f"\r[{bar}] {file_path}/{total_files} ({progress*100:.1f}%)", end='', flush=True)
    
    print(f"Copied {total_files} files")

    
def mountCd():
  drive = "/dev/cdrom"

  os.system(f'mkdir -p {mount}')

  os.system('sudo eject -t') ## Close drive

  with open("/proc/mounts", "r") as proc:
    if mount in proc.read():
      return True, "Already Mounted"
  
  try:
    os.system(f'sudo mount {drive} {mount}')
    if os.path.ismount(mount):
      print("Mounted")
      rip()
  except:
    print("Failed to mount")

  return False, "Failed"



while True:
  input("Press Enter to continue...")
  time.sleep(0.1)
  mountCd()
  rip()
  print("Finished Copy")
