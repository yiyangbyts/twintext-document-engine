---
license: apache-2.0
pipeline_tag: object-detection
tags:
- PaddleOCR
- PaddlePaddle
- ocr
- layout
- layout_detection
language:
- en
- zh
- multilingual
library_name: PaddleOCR
---

## Introduction

**PP-DocLayoutV2** is a dedicated lightweight model for layout analysis, focusing specifically on element detection, classification, and reading order
prediction. 


## **Model Architecture** 

PP-DocLayoutV2 is composed of two sequentially connected networks. The first is an RT-DETR-based detection model that performs layout element detection and classification. The detected bounding boxes and class labels are then passed to a subsequent pointer network, which is responsible for ordering these layout elements.

<div align="center">
<img src="https://huggingface.co/datasets/PaddlePaddle/PaddleOCR-VL_demo/resolve/main/imgs/PP-DocLayoutV2.png" width="800"/>
</div>


## Usage    

### Install Dependencies

Install [PaddlePaddle](https://www.paddlepaddle.org.cn/install/quick) and [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR):

```bash
python -m pip install paddlepaddle-gpu==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
python -m pip install -U "paddleocr[doc-parser]"
python -m pip install https://paddle-whl.bj.bcebos.com/nightly/cu126/safetensors/safetensors-0.6.2.dev0-cp38-abi3-linux_x86_64.whl
```

> For Windows users, please use WSL or a Docker container.


### Basic Usage

Python API usage:

```python
from paddleocr import LayoutDetection

model = LayoutDetection(model_name="PP-DocLayoutV2")
output = model.predict("https://paddle-model-ecology.bj.bcebos.com/paddlex/imgs/demo_image/layout.jpg", batch_size=1, layout_nms=True)
for res in output:
    res.print()
    res.save_to_img(save_path="./output/")
    res.save_to_json(save_path="./output/res.json")
```

**For more usage details and parameter explanations, see the [documentation](https://www.paddleocr.ai/latest/en/version3.x/module_usage/layout_analysis.html).**


## Citation

If you find PaddleOCR-VL helpful, feel free to give us a star and citation.

```bibtex
@misc{cui2025paddleocrvlboostingmultilingualdocument,
      title={PaddleOCR-VL: Boosting Multilingual Document Parsing via a 0.9B Ultra-Compact Vision-Language Model}, 
      author={Cheng Cui and Ting Sun and Suyin Liang and Tingquan Gao and Zelun Zhang and Jiaxuan Liu and Xueqing Wang and Changda Zhou and Hongen Liu and Manhui Lin and Yue Zhang and Yubo Zhang and Handong Zheng and Jing Zhang and Jun Zhang and Yi Liu and Dianhai Yu and Yanjun Ma},
      year={2025},
      eprint={2510.14528},
      archivePrefix={arXiv},
      primaryClass={cs.CV},
      url={https://arxiv.org/abs/2510.14528}, 
}
```