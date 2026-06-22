import subprocess
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parents[1]
SCRIPS_DIR = BASE_DIR / "scripts"

FETCH_SCRIPT = SCRIPS_DIR / "fetch_search_shopping.py"
BUILD_SCRIPT = SCRIPS_DIR / "build_daily_signals.py"

PYTHON_EXE =sys.executable

def run_script(script_path: Path):
    print(f"\n실행시작: {script_path.name}")
    print("-"*60)

    result= subprocess.run(
        [PYTHON_EXE, str(script_path)],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace"
    )

    if result.stdout:
        print(result.stdout)

    if result.returncode != 0:
        if result.stderr:
            print(result.stderr)
        raise RuntimeError(f"{script_path.name} 실행 실패")
    
    print(f"실행 완료: {script_path.name}")
    print("-"*60)


def main():
    start_time = datetime.now()
    print("="*60)
    print("EARLYPICK DAILY PIPELINE START")
    print(f"시작시간:{start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    if not FETCH_SCRIPT.exists():
        raise FileNotFoundError(f"파일이 없습니다.:{FETCH_SCRIPT}")
    
    if not BUILD_SCRIPT.exists():
        raise FileNotFoundError(f"파일이 없습니다.:{BUILD_SCRIPT}")
    
    # 1단계: raw -> processed
    run_script(FETCH_SCRIPT)

    # 2단계: processed -> daily_signals.json
    run_script(BUILD_SCRIPT)

    end_time = datetime.now()
    print("="*60)
    print("EARLYPICK DAILY PIPELINE DONE")
    print(f"종료 시간: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"총 소요 시간: {end_time - start_time}")
    print("=" * 60)


if __name__ == "__main__":
    main()