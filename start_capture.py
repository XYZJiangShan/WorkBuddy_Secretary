import sys, traceback, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')

log = open('start_error.log', 'w', encoding='utf-8')
sys.stderr = log
sys.stdout = log

try:
    import main
    sys.exit(main.main())
except Exception as e:
    traceback.print_exc()
    log.flush()
finally:
    log.close()
