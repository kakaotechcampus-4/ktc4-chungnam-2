# maintenance → 루트

- 배포 때 스케줄러(Cloud Scheduler 등)가 `python -m maintenance.run`을 하루 한 번 부르면 된다(#168). 먼저 `--dry-run`으로 확인.
