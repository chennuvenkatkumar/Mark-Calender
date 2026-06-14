# Mark-Calender

Iteration 1 backbone lives in `src/`:

- `src/ingest/file_ingestor.py` reads local syllabus files.
- `src/ai/gemini_pipeline_controller.py` builds the Gemini prompt and fetches model output.
- `src/validation/string_validator.py` extracts and normalizes the JSON payload.
- `src/export/icalendar_factory.py` turns validated events into an `.ics` file.