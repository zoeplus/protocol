# Downloads and Package Mirrors

## Tsinghua package mirrors

The following Tsinghua endpoints were checked from blue on 2026-08-08 and
returned HTTP 200:

```text
https://pypi.tuna.tsinghua.edu.cn/simple/
https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/
https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r/
https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/
https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/pytorch/
```

Check the required endpoint from blue before starting a large installation:

```bash
curl -L --fail --silent --show-error --output /dev/null \
  --connect-timeout 8 --max-time 25 \
  --write-out '%{http_code} %{time_total}s %{speed_download}B/s\n' \
  https://pypi.tuna.tsinghua.edu.cn/simple/

curl -L --fail --silent --show-error --output /dev/null \
  --connect-timeout 8 --max-time 25 \
  --write-out '%{http_code} %{time_total}s %{speed_download}B/s\n' \
  https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/linux-64/current_repodata.json
```

Prefer explicit per-command configuration instead of changing machine-wide
Conda or pip settings:

```bash
/opt/conda/bin/conda create -n <env-name> python=<version> pip -y \
  --override-channels \
  -c https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main

/opt/conda/bin/conda run --no-capture-output -n <env-name> \
  python -m pip install -r <requirements-file> \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```


## Large downloads

Agents must not start large downloads or long package installations. Prepare a
committed, project-local script and let the operator run it. The script itself
must contain the reproducible settings, mirror selection, retry behavior, log
redirection, and PID recording needed for the operation. Agent responses should
provide only the short script invocation and log-monitoring commands instead of
wrapping a long list of settings in an ad hoc shell command.

Check free space before downloading. Keep Hugging Face `.cache` files until a
download completes; `.incomplete` files are resumable and should not be
deleted during a transient network failure. Download one large artifact at a
time unless bandwidth and disk headroom have been checked.
