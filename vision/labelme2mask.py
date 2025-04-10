import os
import argparse
import json
from labelme import utils
import numpy as np
from glob import glob
import PIL.Image
from PIL import ImageDraw
from pycocotools.coco import COCO
from tqdm import tqdm
import pandas as pd


class Labelme2COCO:
    def __init__(self, labelme_json=[], save_json_path="./coco.json"):
        self.labelme_json = labelme_json
        self.save_json_path = save_json_path
        self.images = []
        self.categories = []
        self.annotations = []
        self.label = []
        self.annID = 1
        self.height = 0
        self.width = 0

    def convert(self):
        self.data_transfer()
        self.data_coco = self.data2coco()
        self.save_json()

    def data_transfer(self):
        for num, json_file in enumerate(self.labelme_json):
            with open(json_file, "r") as fp:
                data = json.load(fp)
                self.images.append(self.image(data, num))
                for shapes in data["shapes"]:
                    label = shapes["label"].split("_")
                    if label not in self.label:
                        self.label.append(label)
                    points = shapes["points"]
                    self.annotations.append(self.annotation(points, label, num))
                    self.annID += 1

        self.label.sort()
        for label in self.label:
            self.categories.append(self.category(label))
        for annotation in self.annotations:
            annotation["category_id"] = self.getcatid(annotation["category_id"])

    def image(self, data, num):
        image = {}
        img = utils.img_b64_to_arr(data["imageData"])
        height, width = img.shape[:2]
        img = None
        image["height"] = height
        image["width"] = width
        image["id"] = num
        image["file_name"] = data["imagePath"].split("/")[-1]

        self.height = height
        self.width = width

        return image

    def category(self, label):
        category = {}
        category["supercategory"] = label[0]
        category["id"] = len(self.categories)
        category["name"] = label[0]
        return category

    def annotation(self, points, label, num):
        annotation = {}
        contour = np.array(points)
        x = contour[:, 0]
        y = contour[:, 1]
        area = 0.5 * np.abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))
        annotation["segmentation"] = [list(np.asarray(points).flatten())]
        annotation["iscrowd"] = 0
        annotation["area"] = area
        annotation["image_id"] = num
        annotation["bbox"] = list(map(float, self.getbbox(points)))
        annotation["category_id"] = label[0]
        annotation["id"] = self.annID
        return annotation

    def getcatid(self, label):
        for category in self.categories:
            if label == category["name"]:
                return category["id"]
        print("label: {} not in categories: {}.".format(label, self.categories))
        exit()
        return -1

    def getbbox(self, points):
        polygons = points
        mask = self.polygons_to_mask([self.height, self.width], polygons)
        return self.mask2box(mask)

    def mask2box(self, mask):
        index = np.argwhere(mask == 1)
        rows = index[:, 0]
        clos = index[:, 1]

        left_top_r = np.min(rows)
        left_top_c = np.min(clos)

        right_bottom_r = np.max(rows)
        right_bottom_c = np.max(clos)

        return [
            left_top_c,
            left_top_r,
            right_bottom_c - left_top_c,
            right_bottom_r - left_top_r,
        ]

    def polygons_to_mask(self, img_shape, polygons):
        mask = np.zeros(img_shape, dtype=np.uint8)
        mask = PIL.Image.fromarray(mask)
        xy = list(map(tuple, polygons))
        ImageDraw.Draw(mask).polygon(xy=xy, outline=1, fill=1)
        mask = np.array(mask, dtype=bool)
        return mask

    def data2coco(self):
        data_coco = {}
        data_coco["images"] = self.images
        data_coco["categories"] = self.categories
        data_coco["annotations"] = self.annotations
        return data_coco

    def save_json(self):
        print("save coco json")
        os.makedirs(os.path.dirname(os.path.abspath(self.save_json_path)), exist_ok=True)
        with open(self.save_json_path, "w") as f:
            json.dump(self.data_coco, f, indent=4)


def create_output_dir(output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)


def load_coco_dataset(coco_json_path):
    return COCO(coco_json_path)


def generate_color_map(cats):
    return {cat['id']: (np.random.randint(0, 256), np.random.randint(0, 256), np.random.randint(0, 256)) for cat in cats}


def save_color_map(color_map, cats, output_dir):
    color_data = [{"category": cat['name'], "r": color_map[cat['id']][0], "g": color_map[cat['id']][1], "b": color_map[cat['id']][2]} for cat in cats]
    color_df = pd.DataFrame(color_data)
    color_df.to_csv(os.path.join(output_dir, 'category_colors.csv'), index=False)


def process_images(coco, color_map, output_dir):
    for img_idx in tqdm(range(len(coco.imgs)), desc="Processing images"):
        cat_ids = coco.getCatIds()
        anns_ids = coco.getAnnIds(imgIds=coco.imgs[img_idx]['id'], catIds=cat_ids, iscrowd=None)
        anns = coco.loadAnns(anns_ids)

        image_info = coco.loadImgs(coco.imgs[img_idx]['id'])[0]
        image_name = image_info['file_name'].split('.')[0]
        height, width = image_info['height'], image_info['width']

        mask = np.zeros((height, width), dtype=np.uint8)

        for annotation in anns:
            category_id = annotation['category_id']
            mask = coco.annToMask(annotation)
            mask[mask == 1] = category_id

            #print(annotation)

        mask = PIL.Image.fromarray(mask)

        mask.save(os.path.join(output_dir, f'{image_name}.png'))


def main(input_dir, output_dir):
    create_output_dir(output_dir)

    coco_json_path = os.path.join(output_dir, "coco.json")
    
    if os.path.exists(coco_json_path):
        print(f"{coco_json_path} already exists. Loading existing file.")
    else:
        print(f"{coco_json_path} does not exist. Generating new COCO JSON file.")
        json_files = glob(os.path.join(input_dir, "*.json"))
        converter = Labelme2COCO(json_files, coco_json_path)
        converter.convert()
    
    coco = load_coco_dataset(coco_json_path)
    cats = coco.loadCats(coco.getCatIds())
    #print(cats)
    color_map = generate_color_map(cats)
    save_color_map(color_map, cats, output_dir)
    process_images(coco, color_map, output_dir)


if __name__ == "__main__":
    #INPUT_DIR: Directory containing labelme json files
    #OUTPUT_DIR: Directory where output files will be stored.
    INPUT_DIR = "data/Robosuite1/Annotations"
    OUTPUT_DIR = "data/Robosuite1/Masks"

    main(INPUT_DIR, OUTPUT_DIR)

