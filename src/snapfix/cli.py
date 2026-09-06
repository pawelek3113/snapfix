from snapfix import MemoriesFixer
from pathlib import Path
from snapfix import LoggerBuilder

if __name__ == "__main__":
    root_dir = input("""
    Enter a root directory (covering every Memories package from Snapchat)
        it should look like that:
                .
                ├── 1
                │   ├── mydata~1774546372096
                │   └── mydata~1774546372096.zip
                ├── 2
                │   ├── mydata~1774546372096-2
                │   └── mydata~1774546372096-2.zip
                ├── 3
                │   ├── mydata~1774546372096-3
                │   └── mydata~1774546372096-3.zip
    > """)

    lg = LoggerBuilder().build(Path("memories_fix.log"))
    with MemoriesFixer(root_dir, dry_run=True, logger=lg) as fixer:
        fixer.run()