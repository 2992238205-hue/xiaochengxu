import os
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path

try:
    from backend.transcription_provider_kimi import KimiCloudTranscriber
    from backend.transcription_provider_aliyun import AliyunSegmentReviewer
    from backend.transcription_service import (
        TranscriptionError,
        apply_terms_to_segments,
        build_output_files,
        merge_term_pairs,
        parse_term_text,
        read_low_conf_threshold,
        review_low_conf_segments,
        transcribe_media_local,
    )
except Exception:
    from transcription_provider_kimi import KimiCloudTranscriber
    from transcription_provider_aliyun import AliyunSegmentReviewer
    from transcription_service import (
        TranscriptionError,
        apply_terms_to_segments,
        build_output_files,
        merge_term_pairs,
        parse_term_text,
        read_low_conf_threshold,
        review_low_conf_segments,
        transcribe_media_local,
    )


def now_iso():
    return datetime.utcnow().isoformat(timespec="seconds")


class TranscriptionWorker:
    def __init__(self, db_conn_factory, output_dir, provider_mode="kimi"):
        self.db_conn_factory = db_conn_factory
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.low_conf_threshold = read_low_conf_threshold()
        self.reviewer = AliyunSegmentReviewer()
        self.kimi = KimiCloudTranscriber()
        self.provider_mode = str(provider_mode or os.getenv("TRANSCRIBE_PROVIDER", "kimi")).strip().lower() or "kimi"
        self._event = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._pipeline_lock = threading.Lock()

    def provider_summary(self):
        if self.provider_mode in {"kimi", "moonshot", "k2.5", "kimi2.5", "cloud"}:
            return {
                "mode": "kimi",
                "label": self.kimi.provider_label(),
                "configured": self.kimi.is_ready(),
            }
        return {
            "mode": "local",
            "label": "Local faster-whisper",
            "configured": True,
        }

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run_loop, name="transcription-worker", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._event.set()

    def notify(self):
        self._event.set()

    def recover_interrupted_jobs(self):
        now = now_iso()
        with self.db_conn_factory() as conn:
            conn.execute(
                """
                UPDATE transcription_jobs
                SET status = 'queued', progress = 0, updated_at = ?
                WHERE status IN ('running', 'reviewing')
                """,
                (now,),
            )

    def _run_loop(self):
        while not self._stop.is_set():
            self._event.clear()
            job = self._claim_next_job()
            if not job:
                self._event.wait(timeout=2.0)
                continue
            self._process_job(job)

    def _claim_next_job(self):
        now = now_iso()
        with self.db_conn_factory() as conn:
            row = conn.execute(
                """
                SELECT * FROM transcription_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            job_id = row["id"]
            conn.execute(
                """
                UPDATE transcription_jobs
                SET status = 'running', progress = 1, started_at = CASE WHEN started_at = '' THEN ? ELSE started_at END,
                    updated_at = ?, error_message = ''
                WHERE id = ?
                """,
                (now, now, job_id),
            )
            refreshed = conn.execute("SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(refreshed) if refreshed else None

    def _update_job_progress(self, job_id, progress):
        now = now_iso()
        bounded = max(0.0, min(100.0, float(progress)))
        with self.db_conn_factory() as conn:
            conn.execute(
                "UPDATE transcription_jobs SET progress = ?, updated_at = ? WHERE id = ?",
                (bounded, now, job_id),
            )

    def _load_terms_for_job(self, conn, job_row):
        global_rows = conn.execute(
            "SELECT source_term, replacement_term FROM transcription_terms ORDER BY LENGTH(source_term) DESC"
        ).fetchall()
        global_pairs = [(str(row["source_term"]), str(row["replacement_term"])) for row in global_rows]
        job_pairs = parse_term_text(job_row.get("term_text") or "")
        return merge_term_pairs(global_pairs=global_pairs, job_pairs=job_pairs)

    def _save_segments(self, conn, job_id, segments):
        conn.execute("DELETE FROM transcription_segments WHERE job_id = ?", (job_id,))
        rows = []
        for segment in segments:
            rows.append(
                (
                    job_id,
                    int(segment.get("segment_index", len(rows))),
                    float(segment.get("start_sec", 0.0) or 0.0),
                    float(segment.get("end_sec", 0.0) or 0.0),
                    str(segment.get("text", "") or ""),
                    float(segment.get("confidence", 0.0) or 0.0),
                    str(segment.get("engine", "local_whisper") or "local_whisper"),
                    int(segment.get("is_low_conf", 0) or 0),
                )
            )
        if rows:
            conn.executemany(
                """
                INSERT INTO transcription_segments (
                    job_id, segment_index, start_sec, end_sec, text, confidence, engine, is_low_conf
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def _complete_job(self, job_id, status, **kwargs):
        now = now_iso()
        fields = {
            "status": status,
            "updated_at": now,
            "finished_at": now if status in {"succeeded", "failed"} else "",
        }
        fields.update(kwargs)
        cols = ", ".join(f"{key} = ?" for key in fields.keys())
        values = list(fields.values()) + [job_id]
        with self.db_conn_factory() as conn:
            conn.execute(f"UPDATE transcription_jobs SET {cols} WHERE id = ?", values)

    def _process_job(self, job):
        job_id = str(job.get("id") or "")
        if not job_id:
            return

        source_path = str(job.get("source_path") or "")
        language = str(job.get("language") or "zh")
        provider_note = ""

        try:
            with self._pipeline_lock:
                with self.db_conn_factory() as conn:
                    term_pairs = self._load_terms_for_job(conn, job)

                use_kimi = self.provider_mode in {"kimi", "moonshot", "k2.5", "kimi2.5", "cloud"}
                if use_kimi:
                    cloud_result = self.kimi.transcribe_media(
                        source_media_path=source_path,
                        language=language,
                        progress_callback=lambda p: self._update_job_progress(job_id, p),
                    )
                    segments = cloud_result["segments"]
                    duration_sec = float(cloud_result.get("duration_sec", 0.0) or 0.0)
                    provider_note = str(cloud_result.get("provider_note") or "")
                    apply_terms_to_segments(segments, term_pairs)
                    for seg in segments:
                        seg["is_low_conf"] = 1 if float(seg.get("confidence", 0.0) or 0.0) < self.low_conf_threshold else 0
                else:
                    local_result = transcribe_media_local(
                        source_media_path=source_path,
                        language=language,
                        term_pairs=term_pairs,
                        low_conf_threshold=self.low_conf_threshold,
                        progress_callback=lambda p: self._update_job_progress(job_id, p),
                    )
                    segments = local_result["segments"]
                    duration_sec = float(local_result.get("duration_sec", 0.0) or 0.0)

                    if self.reviewer.is_ready():
                        try:
                            reviewed = review_low_conf_segments(
                                source_media_path=source_path,
                                segments=segments,
                                reviewer=self.reviewer,
                                language=language,
                                low_conf_threshold=self.low_conf_threshold,
                                progress_callback=lambda p: self._update_job_progress(job_id, p),
                            )
                            segments = reviewed["segments"]
                            provider_note = reviewed.get("note", "")
                        except Exception as review_exc:
                            provider_note = f"阿里云复核失败，已保留本地结果：{review_exc}"
                    elif self.reviewer.is_configured() and not self.reviewer.is_ready():
                        provider_note = "检测到阿里云凭据，但缺少 ALIYUN_ASR_REVIEW_ENDPOINT，跳过复核"

                artifacts = build_output_files(
                    job_id=job_id,
                    segments=segments,
                    output_dir=self.output_dir / job_id,
                )

                low_conf_count = sum(1 for seg in segments if int(seg.get("is_low_conf", 0) or 0) == 1)
                segment_count = len(segments)

                with self.db_conn_factory() as conn:
                    self._save_segments(conn=conn, job_id=job_id, segments=segments)

                self._complete_job(
                    job_id,
                    "succeeded",
                    progress=100,
                    error_message="",
                    duration_sec=duration_sec,
                    segment_count=segment_count,
                    low_conf_count=low_conf_count,
                    output_md_path=str(artifacts["md_path"]),
                    output_txt_path=str(artifacts["txt_path"]),
                    output_srt_path=str(artifacts["srt_path"]),
                    provider_note=provider_note,
                )
        except Exception as exc:
            message = str(exc).strip() or "转写失败"
            if isinstance(exc, TranscriptionError):
                traceback.print_exc()
            self._complete_job(
                job_id,
                "failed",
                progress=0,
                error_message=message,
                provider_note=provider_note,
            )

    def retry_low_confidence(self, job_id):
        with self._pipeline_lock:
            with self.db_conn_factory() as conn:
                row = conn.execute("SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)).fetchone()
                if not row:
                    raise ValueError("任务不存在")
                job = dict(row)
                if job.get("status") in {"running", "reviewing"}:
                    raise ValueError("任务正在执行中，请稍后再试")
                if self.provider_mode in {"kimi", "moonshot", "k2.5", "kimi2.5", "cloud"}:
                    raise ValueError("当前是 Kimi 云端全量转写模式，不支持低置信复核；请直接重传任务。")
                segments_rows = conn.execute(
                    """
                    SELECT segment_index, start_sec, end_sec, text, confidence, engine, is_low_conf
                    FROM transcription_segments
                    WHERE job_id = ?
                    ORDER BY segment_index ASC
                    """,
                    (job_id,),
                ).fetchall()

            segments = [
                {
                    "segment_index": int(r["segment_index"]),
                    "start_sec": float(r["start_sec"]),
                    "end_sec": float(r["end_sec"]),
                    "text": str(r["text"] or ""),
                    "confidence": float(r["confidence"] or 0.0),
                    "engine": str(r["engine"] or "local_whisper"),
                    "is_low_conf": int(r["is_low_conf"] or 0),
                }
                for r in segments_rows
            ]
            if not segments:
                raise ValueError("任务暂无可复核片段")
            if not self.reviewer.is_ready():
                raise ValueError("阿里云复核未就绪，请配置 ALIYUN_ASR_REVIEW_ENDPOINT")

            now = now_iso()
            with self.db_conn_factory() as conn:
                conn.execute(
                    """
                    UPDATE transcription_jobs
                    SET status = 'reviewing', progress = 90, updated_at = ?, error_message = ''
                    WHERE id = ?
                    """,
                    (now, job_id),
                )

            reviewed = review_low_conf_segments(
                source_media_path=str(job.get("source_path") or ""),
                segments=segments,
                reviewer=self.reviewer,
                language=str(job.get("language") or "zh"),
                low_conf_threshold=self.low_conf_threshold,
                progress_callback=lambda p: self._update_job_progress(job_id, p),
            )
            updated_segments = reviewed["segments"]
            artifacts = build_output_files(job_id=job_id, segments=updated_segments, output_dir=self.output_dir / job_id)

            low_conf_count = sum(1 for seg in updated_segments if int(seg.get("is_low_conf", 0) or 0) == 1)

            with self.db_conn_factory() as conn:
                self._save_segments(conn=conn, job_id=job_id, segments=updated_segments)
                conn.execute(
                    """
                    UPDATE transcription_jobs
                    SET status = 'succeeded', progress = 100, updated_at = ?, finished_at = ?,
                        low_conf_count = ?, output_md_path = ?, output_txt_path = ?, output_srt_path = ?,
                        provider_note = ?, error_message = ''
                    WHERE id = ?
                    """,
                    (
                        now_iso(),
                        now_iso(),
                        low_conf_count,
                        str(artifacts["md_path"]),
                        str(artifacts["txt_path"]),
                        str(artifacts["srt_path"]),
                        str(reviewed.get("note") or ""),
                        job_id,
                    ),
                )

            return {
                "ok": True,
                "jobId": job_id,
                "reviewed": int(reviewed.get("reviewed_count", 0) or 0),
                "updated": int(reviewed.get("updated_count", 0) or 0),
                "lowConfCount": low_conf_count,
            }

    def create_job(self, file_name, source_path, language="zh", term_text=""):
        job_id = f"ts-{uuid.uuid4().hex[:12]}"
        now = now_iso()
        with self.db_conn_factory() as conn:
            conn.execute(
                """
                INSERT INTO transcription_jobs (
                    id, file_name, source_path, language, term_text, status,
                    progress, error_message, output_md_path, output_txt_path, output_srt_path,
                    duration_sec, segment_count, low_conf_count, provider_note,
                    created_at, started_at, finished_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'queued', 0, '', '', '', '', 0, 0, 0, '', ?, '', '', ?)
                """,
                (
                    job_id,
                    str(file_name or ""),
                    str(source_path or ""),
                    str(language or "zh"),
                    str(term_text or ""),
                    now,
                    now,
                ),
            )
        self.notify()
        return job_id
