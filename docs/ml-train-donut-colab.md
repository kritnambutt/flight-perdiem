# Training the Donut roster reader on Google Colab

How to run the equivalent of

```bash
make ml-train-donut ARGS="--epochs 10 --synthetic-n 1000"
```

on a **free Google Colab T4 GPU**. This fine-tunes the Donut roster reader
(PD-ML-006) off-Pi, then you download the trained model and drop it onto the Pi.

> **Why not just `make` on Colab?** The `ml-train-donut` target guards on a local
> `.env` (`check-env`) and a `backend/.venv` (`check-venv`) — neither makes sense
> in a Colab notebook. We call the underlying script directly instead; it does the
> exact same thing (`backend/ml/donut/train.py`).

---

## What the training actually needs

- **No `.env`, no database, no Google Drive, no real rosters.** By default the
  script trains on **synthetic rosters** generated on the fly by
  `backend/ml/roster_gen/` — there is **no PII** involved, so it is safe to run on
  a third-party machine like Colab.
- `--synthetic-n 1000` generates 1000 base rosters; each is augmented
  `--aug-per-image` times (default **3**), so you get ~**4000 training images**.
- Mixing in real labelled rosters (`vision.jsonl`) is **optional** and **not
  recommended on Colab** — those images are PII. Leave it out; synthetic-only is
  the intended Colab path.

Output: a HuggingFace `VisionEncoderDecoder` model directory (default
`data/ml/models/donut/`) containing the model weights + processor.

---

## Step 1 — New notebook with a GPU

1. Open <https://colab.research.google.com> → **New notebook**.
2. **Runtime → Change runtime type → Hardware accelerator → T4 GPU → Save.**
3. Verify the GPU is live:

```python
!nvidia-smi
```

You should see a Tesla T4 with ~15 GB memory.

---

## Step 2 — Get the code onto Colab

The repo is **private**, so SSH (`git@…`) won't work from Colab. Use one of:

### Option A — HTTPS clone with a GitHub token (recommended)

Create a fine-grained personal access token with **read** access to the repo
(<https://github.com/settings/tokens>), then:

```python
import os
from getpass import getpass

token = getpass("GitHub token: ")          # paste, not stored in the notebook
os.environ["GIT_TOKEN"] = token
!git clone https://{token}@github.com/kritnambutt/flight-perdiem.git
%cd flight-perdiem
```

### Option B — Upload a zip

On your machine: `git archive --format=zip -o flight-perdiem.zip HEAD`, then in
Colab use the file browser (folder icon) to upload, and:

```python
!unzip -q flight-perdiem.zip -d flight-perdiem
%cd flight-perdiem
```

---

## Step 3 — Install the training dependencies

Colab already ships **torch, torchvision, numpy, OpenCV, and Pillow**. You only
need the HuggingFace pieces (see `backend/requirements-ml.txt`):

```python
!pip install -q "transformers>=4.38.0" "accelerate>=0.27.0"
```

> If a synthetic-image step ever complains about a missing module, install the Pi
> runtime deps too: `!pip install -q opencv-python-headless Pillow numpy`.
> (Colab normally has these already.)

---

## Step 4 — Mount Google Drive (do this before training)

Colab wipes `/content` the moment the runtime disconnects or restarts — if you
run training without mounting Drive first, the model is gone when the session
ends. Mount Drive **before** you start training so every completed epoch is
saved automatically.

```python
from google.colab import drive
drive.mount("/content/drive")
```

Colab will ask you to authorise access — follow the prompt. Once mounted, your
Drive is available at `/content/drive/MyDrive/`.

---

## Step 5 — Run training (output goes straight to Drive)

> **Drive must be mounted (Step 4) before any command that uses
> `/content/drive/…` as `--out`.** The script calls `os.makedirs` on that path
> immediately — if Drive isn't mounted, it fails before training starts. This
> applies to both the smoke test and the full run.

Run the script directly from the `backend/` directory (the script puts `backend/`
on `sys.path` so `perdiem` and `ml` import correctly). Pass `--out` pointing to
Drive so every epoch checkpoint lands there immediately:

```python
%cd /content/flight-perdiem/backend
!python ../scripts/train_donut.py \
    --epochs 10 --synthetic-n 1000 \
    --out /content/drive/MyDrive/perdiem-donut
```

That is the literal equivalent of
`make ml-train-donut ARGS="--epochs 10 --synthetic-n 1000"`.

`save_strategy="epoch"` means a checkpoint is written after **every epoch**, so
even a mid-run disconnect leaves you the last completed epoch safely on Drive.
You can resume from the latest checkpoint by passing `--base-model` pointing to
the saved directory.

### Expected Drive space for the full run

| What | Size |
|------|------|
| Base Donut model download (cached in `/root/.cache`, not on Drive) | ~490 MB |
| Each epoch checkpoint (model weights + optimizer state, fp16) | ~500–800 MB |
| 10 epoch checkpoints | **~6.5 GB** |
| Final best-model save (`model.save_pretrained`) | ~490 MB |
| **Total written to Drive** | **~7 GB** |

Free Google Drive gives you 15 GB — the full run will use roughly half of it.
The script keeps **all** checkpoints by default (`save_total_limit` is not set),
so plan accordingly.

### Smoke-test first (strongly recommended)

A full 10-epoch / 4000-image run is **long** and a free Colab session can
disconnect. Validate the pipeline end-to-end with a tiny run first (Drive must
already be mounted from Step 4):

```python
!python ../scripts/train_donut.py --epochs 1 --synthetic-n 20 \
    --out /content/drive/MyDrive/perdiem-donut-smoke
```

Expected Drive space for the smoke test: **~1.1 GB** (1 checkpoint + final save).

If that finishes and writes a model dir to Drive, scale up to the real run.

### Useful flags

| Flag | Default | Notes |
|------|---------|-------|
| `--epochs` | 5 | Passes over the dataset |
| `--synthetic-n` | 500 | Base synthetic rosters before augmentation |
| `--aug-per-image` | 3 | Augmented variants per base image |
| `--batch-size` | 2 | **Lower to `1` if you hit CUDA out-of-memory** |
| `--lr` | 5e-5 | Learning rate |
| `--out` | `data/ml/models/donut` | Output model directory — **always point to Drive** |
| `--base-model` | `naver-clova-ix/donut-base` | Base checkpoint; can resume from a saved Drive dir |

The script auto-detects the device (CUDA on Colab) and enables fp16 there.

---

## Step 6 — Verify the model was saved

After training (or after a disconnect), confirm your checkpoints are on Drive:

```python
!ls /content/drive/MyDrive/perdiem-donut
```

You should see `config.json`, `pytorch_model.bin` (or shards), and one
subdirectory per completed epoch (e.g. `checkpoint-500`).

---

## What if training already finished but you forgot to mount Drive?

If the run completed but you didn't use `--out` pointing to Drive, zip and
download the model before the session ends or times out:

```python
!zip -qr /content/donut-model.zip /content/flight-perdiem/backend/data/ml/models/donut
from google.colab import files
files.download("/content/donut-model.zip")
```

---

## Step 7 — Deploy to the Pi

1. Copy the downloaded model directory to the Pi at the path your `.env`
   `DONUT_MODEL_PATH` points to (default `data/ml/models/donut`).
2. Enable it: set `DONUT_ENABLED=true` (and pick the backend via
   `OCR_BACKEND=donut` or `OCR_BACKEND=hybrid`) in the Pi's `.env`.
3. Restart the worker so it picks up the new model.

> **ONNX export (optional):** once the HuggingFace model is on the Pi, you can
> convert it to a smaller int8 ONNX graph for faster CPU inference:
> `make ml-export-donut ARGS="--model data/ml/models/donut --out data/ml/models/donut-onnx"`.
> The Donut reader dispatches to onnxruntime when `*.onnx` files are present, or
> falls back to torch when only a HuggingFace model dir is found — so the HF model
> is fully usable as-is without the ONNX step.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `CUDA out of memory` | Re-run with `--batch-size 1`. |
| `ERROR: No module named 'transformers'` | Re-run Step 3; confirm the install cell succeeded. |
| Training runs on CPU (very slow) | GPU wasn't attached — redo Step 1, then `!nvidia-smi`. |
| Session disconnects mid-run | Mount Drive before training (Step 4) and use `--out` pointing to Drive (Step 5); resume from the last epoch checkpoint. |
| `ModuleNotFoundError: perdiem` / `ml` | Make sure you're in `flight-perdiem/backend/` when launching (Step 5). |

---

## Notes & cost

- **Free** on Colab's T4. A 10-epoch run over ~4000 images is on the order of
  hours — budget for it, and prefer the Drive-mounted approach so you never lose
  progress. Start with the smoke test.
- Everything here is synthetic-data training — no roster PII leaves your machine.
- Reference: `scripts/train_donut.py`, `backend/ml/donut/train.py`,
  `backend/requirements-ml.txt`, and the `ml-train-donut` target in the `Makefile`.
