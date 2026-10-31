# books/

One folder per company, created with `python -m engine new <slug> --erp <qbo|xero|intacct|netsuite>`.

**Everything here except this README is git-ignored and must never be pushed to the public repository.** For version history of your notes, make `books/` its own private repo:

```bash
cd books && git init && git remote add origin <your PRIVATE repo url>
```

The parent repo ignores `books/*`, so the two repos don't collide.
