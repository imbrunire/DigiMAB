# DigiMAB
Repository containing material related to DigiMAB - CNSL UniMC project on automatic extraction of metadata starting from different sources (handwritten, audios)

# 📜 Agentic Framework for Archival Processing (pipeline_manuscripts folder)

## ⚙️ Architecture Overview

```text
                +----------------------+
                |     Input Data       |
                |----------------------|
                | - Manuscript images  |
                | - Manual metadata    |
                +----------+-----------+
                           |
                           v

        +----------------------------------------+
        |  External Technical Metadata Extraction|
        |----------------------------------------|
        | - EXIFTool                             |
        | - Format, size, device                 |
        | - MD5 hash                             |
        +------------------+---------------------+
                           |
                           v

        +----------------------------------------+
        | Manual Metadata Ingestion              |
        |----------------------------------------|
        | - Expert-curated metadata              |
        | - Parsed from structured documents     |
        | - Converted into JSON                  |
        +------------------+---------------------+
                           |
                           v

                +----------------------+
                |   Preprocessing      |
                |----------------------|
                | - Image enhancement  |
                | - Base64 encoding    |
                +----------+-----------+
                           |
                           v

        +-------------------------------------------+
        |        Shared Context / Memory            |
        |-------------------------------------------|
        | - Essential metadata (trusted)            |
        | - Technical metadata                     |
        | - AI-enriched metadata                   |
        +------------------+------------------------+
                           |
      -------------------------------------------------------
      |                         |                           |
      v                         v                           v

+----------------+     +----------------+        +----------------+
| Metadata Agent |     | Transcription  |        | Regesto Agent  |
|                |     | Agent          |        |                |
|----------------|     |----------------|        |----------------|
| Enrichment     |     | Diplomatic     |        | Archival       |
| & analysis     |     | transcription  |        | summary        |
|                |     | + XML tagging  |        | (≤ 50 words)   |
+--------+-------+     +--------+-------+        +--------+-------+
         |                      |                         |
         -------------------------------------------------
                           |
                           v

                +------------------------+
                | METS XML Generator     |
                |------------------------|
                | Eco-MIC compliant      |
                | structured output      |
                +------------------------+
```

More information can be found [here](pipeline_manuscripts/pipeline.md)




