# MiniMind runtime image

The image fetches MiniMind source revision `512eed0b6556e741d80864f054d45d271459772a`
from the upstream Apache-2.0 repository during the build. Model weights are not copied
into the image or Git; Compose mounts `minimind/out` read-only at runtime.

The default command serves `full_sft_768.pth` on port `8998` using the CPU. Keep the
matching weight at `minimind/out/full_sft_768.pth` before starting the service.
