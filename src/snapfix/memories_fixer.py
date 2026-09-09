import re
from dataclasses import dataclass
from datetime import date, datetime, time
from logging import Logger
from pathlib import Path

import ffmpeg
from exiftool import ExifToolHelper
from PIL import Image

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
    def __init__(
        self,
        root_dir: str | Path,
        dry_run: bool = False,
        logger: Logger | None = None,
        keep_backups: bool = False,
    ):
        self.root_dir = Path(root_dir)
        if not self.root_dir.is_dir():
            raise NotADirectoryError(
                f"root_dir does not exist or is not a directory: {self.root_dir}"
            )
        self._et: ExifToolHelper | None = None
        self.dry_run = dry_run
        self.logger = logger
        self.keep_backups = keep_backups

    def __enter__(self):
        common_args = [] if self.keep_backups else ["-overwrite_original"]
        self._et = ExifToolHelper(common_args=common_args)
        self._et.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._et is not None:
            self._et.__exit__(exc_type, exc_val, exc_tb)
        return False

    def _ensure_started(self) -> ExifToolHelper:
        if self._et is None:
            raise RuntimeError(
                "MemoriesFixer must be used as a context manager (use 'with')"
            )
        return self._et

    def find_pairs(self) -> list[MemoryPair]:
        pairs: dict[str, MemoryPair] = {}

        self._collect_into(pairs, pattern="*-main.*", kind="main")
        self._collect_into(pairs, pattern="*-overlay.*", kind="overlay")

        self._log_unpaired(pairs)

        return list(pairs.values())

    def _collect_into(
        self, pairs: dict[str, MemoryPair], pattern: str, kind: str
    ) -> None:
        for path in self.root_dir.rglob(pattern):
            match = FILENAME_PATTERN.match(path.name)
            if not match:
                if self.logger:
                    self.logger.warning(
                        "Filename does not match expected pattern, skipping: %s", path
                    )
                continue

            uuid = match.group("uuid").upper()
            date = datetime.strptime(match.group("date"), "%Y-%m-%d").date()
            pair = pairs.setdefault(uuid, MemoryPair(date=date, uuid=uuid))

            existing = getattr(pair, f"{kind}_path")
            if existing is not None and existing != path:
                if self.logger:
                    self.logger.warning(
                        "Duplicate %s file for UUID %s: keeping %s, ignoring %s",
                        kind,
                        uuid,
                        existing,
                        path,
                    )
                continue

            setattr(pair, f"{kind}_path", path)

    def _log_unpaired(self, pairs: dict[str, MemoryPair]) -> None:
        for pair in pairs.values():
            if pair.main_path is None:
                if self.logger:
                    self.logger.warning(
                        "Overlay without matching main file: %s", pair.overlay_path
                    )
            elif pair.overlay_path is None:
                if self.logger:
                    self.logger.debug(
                        "Main file without overlay (expected for some memories): %s",
                        pair.main_path,
                    )

    def _determine_target_datetime(
        self, pair: MemoryPair, metadata: dict
    ) -> datetime | None:
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
                    self.logger.info(
                        "[DRY RUN] Would set EXIF tags %s on %s", tags, main_path
                    )
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
                self.logger.info(
                    "[DRY RUN] Would set filesystem dates %s on %s", formatted, path
                )
            return

        et.set_tags(files=str(path), tags=tags)
        if self.logger:
            self.logger.info("Set filesystem dates on %s: %s", path, formatted)

    def _print_summary(self, fixed: int, skipped: int, label: str = "Fixed") -> None:
        if self.logger is None:
            return
        self.logger.info("")
        self.logger.info("Done! %s %d files, skipped %d.", label, fixed, skipped)

    def fix_dates(self):
        et = self._ensure_started()
        fixed = 0
        skipped = 0

        for pair in self.find_pairs():
            source_path = pair.main_path or pair.overlay_path
            if source_path is None:
                skipped += 1
                continue  # shouldn't happen in practice

            metadata = et.get_metadata(files=str(source_path))[0]

            target_datetime = self._determine_target_datetime(pair, metadata)
            if target_datetime is None:
                if self.logger:
                    self.logger.warning(
                        "Could not determine target date for UUID %s, skipping",
                        pair.uuid,
                    )
                skipped += 1
                continue

            self._apply_dates(pair, target_datetime)
            fixed += 1

        self._print_summary(fixed=fixed, skipped=skipped)

    def _compose_pair(self, pair: MemoryPair, output_dir: Path) -> None:
        assert pair.main_path is not None and pair.overlay_path is not None
        et = self._ensure_started()

        metadata = et.get_metadata(files=str(pair.main_path))[0]
        target_datetime = self._determine_target_datetime(pair, metadata)
        if target_datetime is None:
            if self.logger:
                self.logger.warning(
                    "Could not determine date for composite, skipping UUID %s",
                    pair.uuid,
                )
            return

        output_path = output_dir / f"{pair.main_path.stem}_composed.jpg"

        if self.dry_run:
            if self.logger:
                self.logger.info("[DRY RUN] Would create composite %s", output_path)
            return

        base = Image.open(pair.main_path).convert("RGBA")
        overlay = Image.open(pair.overlay_path).convert("RGBA")

        if overlay.size != base.size:
            overlay = overlay.resize(base.size)

        composed = Image.alpha_composite(base, overlay).convert("RGB")
        composed.save(output_path, "JPEG")

        self._write_main_tags(
            output_path, target_datetime.strftime("%Y:%m:%d %H:%M:%S")
        )

    def _compose_video_pair(self, pair: MemoryPair, output_dir: Path) -> None:
        assert pair.main_path is not None and pair.overlay_path is not None

        et = self._ensure_started()
        metadata = et.get_metadata(files=str(pair.main_path))[0]
        target_datetime = self._determine_target_datetime(pair, metadata)
        if target_datetime is None:
            if self.logger:
                self.logger.warning(
                    "Could not determine date for video composite, skipping UUID %s",
                    pair.uuid,
                )
            return

        output_path = output_dir / f"{pair.main_path.stem}_composed.mp4"

        if self.dry_run:
            if self.logger:
                self.logger.info(
                    "[DRY RUN] Would create video composite %s", output_path
                )
            return

        video_input = ffmpeg.input(str(pair.main_path))
        overlay_input = ffmpeg.input(str(pair.overlay_path))

        composed_video = ffmpeg.filter(
            [video_input.video, overlay_input.video],
            "overlay",
        )

        (
            ffmpeg.output(
                composed_video,
                video_input.audio,
                str(output_path),
                vcodec="libx264",
                crf=15,
                acodec="copy",
            )
            .overwrite_output()
            .run(quiet=True)
        )

        formatted = target_datetime.strftime("%Y:%m:%d %H:%M:%S")
        et.set_tags(
            files=str(output_path),
            tags={
                "QuickTime:CreateDate": formatted,
                "QuickTime:ModifyDate": formatted,
                "File:FileCreateDate": formatted,
                "File:FileModifyDate": formatted,
            },
        )
        if self.logger:
            self.logger.info(
                "Created video composite %s with date %s", output_path, formatted
            )

    def compose_all(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)

        composed = 0
        skipped = 0

        for pair in self.find_pairs():
            if pair.main_path is None or pair.overlay_path is None:
                if self.logger:
                    self.logger.debug(
                        "Skipping compose (no overlay) for UUID %s", pair.uuid
                    )
                skipped += 1
                continue

            suffix = pair.main_path.suffix.lower()
            if suffix == ".jpg":
                self._compose_pair(pair, output_dir)
                composed += 1
            elif suffix == ".mp4":
                self._compose_video_pair(pair, output_dir)
                composed += 1
            else:
                if self.logger:
                    self.logger.warning(
                        "Unrecognized main file type for compose: %s", pair.main_path
                    )
                    skipped += 1

        self._print_summary(fixed=composed, skipped=skipped, label="Composed")
