# C3 Temporary Maintenance Branch Note

A temporary branch/PR may be used to execute the already-reviewed regression patch workflow because GitHub does not activate a newly introduced workflow on an already-open pull request. The temporary PR is execution infrastructure only: it must not merge to `main`, and its resulting commit may only fast-forward `phase-c3-installation-extras-ux` before the workflow is deleted.
