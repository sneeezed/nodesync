"""
Mixin: commit history queries.
"""


class HistoryMixin:
    def log(self, n: int = 30) -> list:
        """
        Return up to n commits as a list of dicts:
            { hash, full_hash, subject, author, date, decorations }
        decorations is a list of ref names (branch/tag) pointing at that commit.
        """
        fmt = '%H\x1f%s\x1f%an\x1f%ai\x1f%D'
        r = self._run('log', f'-{n}', f'--pretty=format:{fmt}', check=False)
        if r.returncode != 0 or not r.stdout.strip():
            return []
        entries = []
        for line in r.stdout.strip().split('\n'):
            parts = line.split('\x1f')
            if len(parts) >= 4:
                raw_decorations = parts[4].strip() if len(parts) >= 5 else ''
                decorations = []
                if raw_decorations:
                    for d in raw_decorations.split(','):
                        d = d.strip()
                        # "HEAD -> main" → extract "main"
                        if '->' in d:
                            d = d.split('->')[-1].strip()
                        if d and d != 'HEAD':
                            decorations.append(d)
                entries.append({
                    'full_hash':   parts[0],
                    'hash':        parts[0][:8],
                    'subject':     parts[1],
                    'author':      parts[2],
                    'date':        parts[3][:10],   # YYYY-MM-DD only
                    'decorations': decorations,
                })
        return entries

    def log_for_file(self, filepath: str, n: int = 300) -> set:
        """Return a set of full commit hashes that touched *filepath*.

        *filepath* is relative to the repo root, e.g. 'nodes/MyGroup.json'.
        Returns an empty set if there are no commits or the file was never
        committed.
        """
        r = self._run(
            'log', f'--max-count={n}', '--format=%H', '--', filepath,
            check=False,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return set()
        return set(r.stdout.strip().splitlines())
