# Privacy

Resume files contain sensitive personal information. This application is local-first, but it is
not fully offline when a DeepSeek API key is configured.

## Data that stays local

- Original PDF, DOCX, image, and supplementary files
- SQLite database, extraction cache, Excel reports, and copied candidate packages
- DeepSeek API key, stored in the operating-system credential manager
- Absolute local paths

## Data sent to DeepSeek

After an explicit confirmation for each run, the application sends the job criteria and extracted
resume text required for semantic analysis. It replaces local filenames with opaque file IDs and,
by default, redacts common names, phone numbers, email addresses, Chinese identity numbers, and
address fields. Automated redaction cannot guarantee removal of every personal identifier.

Users are responsible for having a lawful basis and appropriate authorization to process candidate
data and to use the configured model provider. The product does not make final employment decisions;
all recommendations and uncertain items require human review.

## Reports and support

Do not attach real resumes, API keys, databases, logs, or generated Excel files to public GitHub
issues. Reproduce problems with synthetic data and remove identifying information from screenshots.
