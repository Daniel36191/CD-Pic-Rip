import asyncio
import os
import shutil
import time
from pathlib import Path
from datetime import datetime
from asyncio import Semaphore, Queue
import sys
from typing import List, Tuple
import signal

mount = "/home/daniel/mount/cdrom"
output = "./out"
root = Path(mount) / "Pictures"
uploadConcurrency = 10
copyConcurrency = 10

shouldStop = False


def signalHandler(signum, frame):
    global shouldStop
    print("\nCleaning up...")
    shouldStop = True


signal.signal(signal.SIGINT, signalHandler)
signal.signal(signal.SIGTERM, signalHandler)


class ProgressDisplay:
    def __init__(self):
        self.lastLines = 0
        self.started = False

    def start(self):
        if not self.started:
            self.started = True

    def update(
        self,
        copyProgress,
        copyCurrent,
        copyTotal,
        copyErrors,
        uploadProgress,
        uploadCurrent,
        uploadTotal,
        uploadErrors,
        barLength=50,
    ):

        copyFilled = int(barLength * copyProgress)
        uploadFilled = int(barLength * uploadProgress)

        copyBar = ("\033[32m" + ("█" * copyFilled)) + "\033[0m" + ("\033[37m" +"░" * (barLength - copyFilled)) + "\033[0m"
        uploadBar = ("\033[34m" + ("█" * uploadFilled)) + "\033[0m" + ("\033[37m" + "░" * (barLength - uploadFilled)) + "\033[0m"

        copyPercent = copyProgress * 100
        uploadPercent = uploadProgress * 100

        print(
            f"Copy:    [{copyBar}] {copyCurrent}/{copyTotal} ({copyPercent:.1f}%) | Errors: {copyErrors}"
        )
        print(
            f"Upload:  [{uploadBar}] {uploadCurrent}/{uploadTotal} ({uploadPercent:.1f}%) | Errors: {uploadErrors}"
        )
        self.lastLines = 3

        print("\r\033[3A")

    def finish(self):
        if self.started and self.lastLines > 0:
            print(f"\033[{self.lastLines}A", end="")
            print("\033[2K" * self.lastLines, end="")
            print(f"\033[{self.lastLines}B", end="")
            self.lastLines = 0


progress = ProgressDisplay()


async def runCommand(cmd, ignoreErrors=False):
    global shouldStop
    if shouldStop:
        return -1, "", "Interrupted"

    process = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0 and not ignoreErrors:
        if stderr:
            errorMsg = stderr.decode().strip()
            if "not mounted" not in errorMsg:
                print(f"Command '{cmd}' failed: {errorMsg}")
    return (
        process.returncode,
        stdout.decode() if stdout else "",
        stderr.decode() if stderr else "",
    )


async def scanFiles(rootPath: Path) -> List[Path]:
    global shouldStop
    if shouldStop:
        return []

    def scan():
        files = []
        for filePath in rootPath.rglob("*"):
            if shouldStop:
                break
            if filePath.is_file() and "index" not in filePath.name.lower():
                files.append(filePath)
        return files

    return await asyncio.get_event_loop().run_in_executor(None, scan)


async def copyAndQueueFile(
    filePath: Path, outputDir: str, semaphore: Semaphore, fileQueue: Queue
):
    global shouldStop
    if shouldStop:
        return None, None, "Interrupted"

    async with semaphore:
        try:

            modTime = datetime.fromtimestamp(os.path.getmtime(filePath))

            baseName = modTime.strftime("%Y%m%d_%H%M%S")
            suffix = filePath.suffix
            newName = f"{baseName}{suffix}"
            newPath = os.path.join(outputDir, newName)

            counter = 1
            while os.path.exists(newPath):
                newName = f"{baseName}_{counter}{suffix}"
                newPath = os.path.join(outputDir, newName)
                counter += 1

            await asyncio.to_thread(shutil.copy2, filePath, newPath)

            await fileQueue.put(newPath)

            return filePath, newPath, None

        except Exception as e:
            return filePath, None, str(e)


async def uploadWorker(
    workerId: int,
    uploadQueue: Queue,
    uploadSemaphore: Semaphore,
    uploadedCounter,
    failedCounter,
    uploadTotalCounter,
):
    global shouldStop

    while not shouldStop:
        try:

            try:
                filePath = await asyncio.wait_for(uploadQueue.get(), timeout=1.0)
            except asyncio.TimeoutError:

                continue

            if filePath is None:
                uploadQueue.task_done()
                break

            async with uploadSemaphore:
                cmd = f'immich upload "{filePath}"'
                returncode, stdout, stderr = await runCommand(cmd, ignoreErrors=True)

            if returncode == 0:
                uploadedCounter["count"] += 1
            else:
                failedCounter["count"] += 1

            uploadTotalCounter["count"] += 1

            uploadQueue.task_done()

        except Exception as e:

            failedCounter["count"] += 1
            uploadTotalCounter["count"] += 1
            if uploadQueue:
                uploadQueue.task_done()


async def ripAndUpload():
    global shouldStop, progress

    os.makedirs(output, exist_ok=True)

    print("Scanning files...", end="", flush=True)
    fileList = await scanFiles(root)
    totalFiles = len(fileList)
    print(f" Found {totalFiles} files")

    if totalFiles == 0 or shouldStop:
        return 0, 0

    progress.start()

    uploadQueue = Queue(maxsize=50)
    copySemaphore = Semaphore(copyConcurrency)
    uploadSemaphore = Semaphore(uploadConcurrency)

    copiedCounter = {"count": 0}
    uploadedCounter = {"count": 0}
    failedUploadCounter = {"count": 0}
    failedCopyCounter = {"count": 0}
    uploadTotalCounter = {"count": 0}
    fileErrors = []

    numUploadWorkers = min(uploadConcurrency, totalFiles)
    uploadTasks = []
    for i in range(numUploadWorkers):
        task = asyncio.create_task(
            uploadWorker(
                i,
                uploadQueue,
                uploadSemaphore,
                uploadedCounter,
                failedUploadCounter,
                uploadTotalCounter,
            )
        )
        uploadTasks.append(task)

    copyTasks = []
    for filePath in fileList:
        if shouldStop:
            break

        task = asyncio.create_task(
            copyAndQueueFile(filePath, output, copySemaphore, uploadQueue)
        )
        copyTasks.append(task)

    lastUpdate = 0
    updateInterval = 0.1

    for coro in asyncio.as_completed(copyTasks):
        if shouldStop:
            break

        result = await coro
        if isinstance(result, Exception):
            failedCopyCounter["count"] += 1
            fileErrors.append(("Unknown", str(result)))
        elif result:
            filePath, newPath, error = result
            if error:
                failedCopyCounter["count"] += 1
                fileErrors.append((str(filePath), error))
            else:
                copiedCounter["count"] += 1

        currentTime = time.time()
        if currentTime - lastUpdate >= updateInterval:

            copyProcessed = copiedCounter["count"] + failedCopyCounter["count"]
            copyProgress = copyProcessed / totalFiles if totalFiles > 0 else 0

            uploadProcessed = uploadTotalCounter["count"]

            uploadTarget = copiedCounter["count"]
            uploadProgress = uploadProcessed / uploadTarget if uploadTarget > 0 else 0

            progress.update(
                copyProgress,
                copyProcessed,
                totalFiles,
                failedCopyCounter["count"],
                uploadProgress,
                uploadProcessed,
                uploadTarget,
                failedUploadCounter["count"],
            )

            lastUpdate = currentTime

    for _ in range(numUploadWorkers):
        if not shouldStop:
            await uploadQueue.put(None)

    uploadTarget = copiedCounter["count"]
    while uploadTotalCounter["count"] < uploadTarget and not shouldStop:
        currentTime = time.time()
        if currentTime - lastUpdate >= updateInterval:

            copyProgress = 1.0

            uploadProcessed = uploadTotalCounter["count"]
            uploadProgress = uploadProcessed / uploadTarget if uploadTarget > 0 else 0

            progress.update(
                copyProgress,
                totalFiles,
                totalFiles,
                failedCopyCounter["count"],
                uploadProgress,
                uploadProcessed,
                uploadTarget,
                failedUploadCounter["count"],
            )

            lastUpdate = currentTime

        await asyncio.sleep(0.1)

    progress.update(
        1.0,
        totalFiles,
        totalFiles,
        failedCopyCounter["count"],
        1.0,
        copiedCounter["count"],
        copiedCounter["count"],
        failedUploadCounter["count"],
    )

    await asyncio.sleep(0.5)
    progress.finish()

    if not shouldStop:
        await uploadQueue.join()

    for task in uploadTasks:
        task.cancel()

    if uploadTasks:
        await asyncio.gather(*uploadTasks, return_exceptions=True)

    copied = copiedCounter["count"]
    uploaded = uploadedCounter["count"]
    failedCopy = failedCopyCounter["count"]
    failedUpload = failedUploadCounter["count"]

    print("\n" + "=" * 70)
    print("Summary:")
    print(f"  Files found: {totalFiles}")
    print(f"  Successfully copied: {copied}")
    print(f"  Copy errors: {failedCopy}")
    print(f"  Successfully uploaded: {uploaded}")
    print(f"  Upload duplicates: {failedUpload}")
    print("=" * 70)

    print("Checking Photos...")
    returncode, stdout, stderr = await runCommand(f"imv {output}", ignoreErrors=True)

    if fileErrors:
        print(f"\nCopy errors (first 5):")
        for filePath, error in fileErrors[:5]:
            print(f"  {os.path.basename(filePath)}: {error}")

    if uploaded > 0:
        print(f"\nRemoving {uploaded} uploaded files...", end="\n", flush=True)

        def removeUploaded():
            removed = 0
            for filePath in Path(output).glob("*"):
                if filePath.is_file():
                    try:
                        os.unlink(filePath)
                        removed += 1
                    except:
                        pass
            return removed

        removed = await asyncio.get_event_loop().run_in_executor(None, removeUploaded)
        print(f" removed {removed} files")

    return uploaded, failedUpload


async def mountCd():
    drive = "/dev/cdrom"
    driveSpeed = 48

    os.makedirs(mount, exist_ok=True)

    await runCommand(f"sudo eject -t -x {driveSpeed}", ignoreErrors=True)

    await asyncio.sleep(1)

    try:
        with open("/proc/mounts", "r") as proc:
            if mount in proc.read():
                print("Already mounted")
                return True, "Already Mounted"
    except:
        pass

    returncode, stdout, stderr = await runCommand(f"sudo mount {drive} {mount}")

    if returncode == 0:

        await asyncio.sleep(0.5)
        if os.path.ismount(mount):
            print("Successfully mounted")
            return True, "Mounted"

    print("Failed to mount")
    return False, "Failed to mount"


async def unmount():

    print("\nUnmounting...", end="\n", flush=True)

    returncode, stdout, stderr = await runCommand(
        f"sudo umount {mount}", ignoreErrors=True
    )

    await asyncio.sleep(0.5)

    try:
        with open("/proc/mounts", "r") as f:
            if mount in f.read():
                print(" failed (still mounted)")
                return False
    except:
        pass

    await runCommand("sudo eject", ignoreErrors=True)
    print("Ejected...")
    return True


async def waitForUserInput():

    loop = asyncio.get_event_loop()
    future = loop.create_future()

    def getInput():
        try:
            result = input("\nInsert CD and press \'Enter\'")
            loop.call_soon_threadsafe(future.set_result, result)
        except Exception as e:
            loop.call_soon_threadsafe(future.set_exception, e)

    loop.run_in_executor(None, getInput)

    try:
        result = await future
        return result
    except asyncio.CancelledError:
        raise


async def mainLoop():

    global shouldStop

    await unmount()

    while not shouldStop:
        try:

            userInput = await waitForUserInput()

            if userInput is None or userInput.strip().lower() == "q":
                print("Exiting...")
                break

        except KeyboardInterrupt:
            print("\nExiting...")
            break

        print("\nMounting CD...", end="", flush=True)
        success, message = await mountCd()
        if not success:
            print(f" Failed: {message}")
            continue
        print(" OK")

        uploaded, failed = await ripAndUpload()

        if uploaded > 0:
            print(f"\nSuccessfully processed {uploaded} files")
            if failed > 0:
                print(f"Warning: {failed} files failed to upload")
        else:
            print("\nNo files were uploaded")

        await unmount()

        returncode, stdout, stderr = await runCommand(f"clear")

async def main():
    try:
        await mainLoop()
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


asyncio.run(main())
