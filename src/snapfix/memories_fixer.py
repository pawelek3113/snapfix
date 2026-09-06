from exiftool import ExifToolHelper
from pathlib import Path
from logging import Logger
from datetime import datetime, time, date

from dataclasses import dataclass
from pathlib import Path
import re


FILENAME_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<uuid>[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12})-(?P<kind>main|overlay)\.\w+$",
    re.IGNORECASE,
)

QUICKTIME_DATE_FORMAT = "%Y:%m:%d %H:%M:%S"


@dataclass
class MemoryPair:
    uuid: str
    date: date 
    main_path: Path | None = None
    overlay_path: Path | None = None

class MemoriesFixer:
    def __init__(self, root_dir: str | Path, dry_run: bool = False, logger: Logger | None = None):
        self.root_dir = Path(root_dir)
        if not self.root_dir.is_dir():
            raise NotADirectoryError(f"root_dir does not exist or is not a directory: {self.root_dir}")
        self._et: ExifToolHelper | None = None
        self.dry_run = dry_run
        self.logger = logger

    def __enter__(self):
        self._et = ExifToolHelper()
        self._et.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._et is not None:
            self._et.__exit__(exc_type, exc_val, exc_tb)
        return False

    def _ensure_started(self) -> ExifToolHelper:
        if self._et is None:
            raise RuntimeError("MemoriesFixer must be used as a context manager (use 'with')")
        return self._et
    
    def find_pairs(self) -> list[MemoryPair]:
        pairs: dict[str, MemoryPair] = {}

        self._collect_into(pairs, pattern="*-main.*", kind="main")
        self._collect_into(pairs, pattern="*-overlay.*", kind="overlay")

        self._log_unpaired(pairs)

        return list(pairs.values())

    def _collect_into(self, pairs: dict[str, MemoryPair], pattern: str, kind: str) -> None:
        for path in self.root_dir.rglob(pattern):
            match = FILENAME_PATTERN.match(path.name)
            if not match:
                if self.logger: 
                    self.logger.warning("Filename does not match expected pattern, skipping: %s", path)
                continue

            uuid = match.group("uuid").upper()
            date = datetime.strptime(match.group("date"), "%Y-%m-%d").date()
            pair = pairs.setdefault(uuid, MemoryPair(date=date, uuid=uuid))

            existing = getattr(pair, f"{kind}_path")
            if existing is not None and existing != path:
                if self.logger: 
                    self.logger.warning(
                        "Duplicate %s file for UUID %s: keeping %s, ignoring %s",
                        kind, uuid, existing, path,
                    )
                continue

            setattr(pair, f"{kind}_path", path)

    def _log_unpaired(self, pairs: dict[str, MemoryPair]) -> None:
        for pair in pairs.values():
            if pair.main_path is None:
                if self.logger:
                    self.logger.warning("Overlay without matching main file: %s", pair.overlay_path)
            elif pair.overlay_path is None:
                if self.logger:
                    self.logger.debug("Main file without overlay (expected for some memories): %s", pair.main_path)


    def _determine_target_datetime(self, pair: MemoryPair, metadata: dict) -> datetime | None:
        file_type = metadata.get("File:FileType")

        if file_type == "MP4":
            return self._datetime_from_quicktime(metadata)

        return self._datetime_from_filename(pair)


    def _datetime_from_quicktime(self, metadata: dict) -> datetime | None:
        raw_value = metadata.get("QuickTime:CreateDate")
        if not raw_value:
            return None
        try:
            return datetime.strptime(raw_value, QUICKTIME_DATE_FORMAT)
        except ValueError:
            return None

    def _datetime_from_filename(self, pair: MemoryPair) -> datetime | None:
        return datetime.combine(pair.date, time(hour=12))


    def _apply_dates(self, pair: MemoryPair, target_datetime: datetime) -> None:
        et = self._ensure_started()
        formatted = target_datetime.strftime("%Y:%m:%d %H:%M:%S")

        if pair.main_path is not None:
            self._write_main_tags(pair.main_path, formatted)

        if pair.overlay_path is not None:
            self._write_filesystem_tags(pair.overlay_path, formatted)


    def _write_main_tags(self, main_path: Path, formatted: str) -> None:
        et = self._ensure_started()
        file_type_is_jpeg = main_path.suffix.lower() == ".jpg"

        if file_type_is_jpeg:
            tags = {
                "EXIF:DateTimeOriginal": formatted,
                "EXIF:CreateDate": formatted,
                "EXIF:ModifyDate": formatted,
            }
            if self.dry_run:
                if self.logger:
                    self.logger.info("[DRY RUN] Would set EXIF tags %s on %s", tags, main_path)
            else:
                et.set_tags(files=str(main_path), tags=tags)
                if self.logger:
                    self.logger.info("Set EXIF tags on %s: %s", main_path, formatted)

        self._write_filesystem_tags(main_path, formatted)


    def _write_filesystem_tags(self, path: Path, formatted: str) -> None:
        et = self._ensure_started()
        tags = {
            "File:FileCreateDate": formatted,
            "File:FileModifyDate": formatted,
        }

        if self.dry_run:
            if self.logger:
                self.logger.info("[DRY RUN] Would set filesystem dates %s on %s", formatted, path)
            return

        et.set_tags(files=str(path), tags=tags)
        if self.logger:
            self.logger.info("Set filesystem dates on %s: %s", path, formatted)


    def run(self):
        et = self._ensure_started()

        for pair in self.find_pairs():
            source_path = pair.main_path or pair.overlay_path
            if source_path is None:
                continue  # shouldn't happen in practice

            metadata = et.get_metadata(files=str(source_path))[0]

            target_datetime = self._determine_target_datetime(pair, metadata)
            if target_datetime is None:
                if self.logger:
                    self.logger.warning("Could not determine target date for UUID %s, skipping", pair.uuid)
                continue

            self._apply_dates(pair, target_datetime)
