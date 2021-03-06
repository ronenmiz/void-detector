'''Run from project root, or whichever dir that contains the labels dir'''

import argparse
import os
import os.path as osp
from glob import glob

import numpy as np
import torch
import torch.nn.functional as F
import torchvision.transforms as transforms
from PIL import Image
from torch.autograd import Variable
import cv2
from tqdm import tqdm

from torchcv.models.ssd import SSDBoxCoder

from torchcv.models.void_models import FPNSSD512_2
from utils import videoid2videoname


def get_ground_truth(line):
    splited = line.strip().split()
    fname = splited[0]
    boxes = []
    labels = []
    num_boxes = (len(splited) - 1) // 5
    for i in range(num_boxes):
        xmin = int(np.round(float((splited[1+5*i])))) - 1
        ymin = int(np.round(float((splited[2+5*i])))) - 1
        xmax = int(np.round(float((splited[3+5*i])))) - 1
        ymax = int(np.round(float((splited[4+5*i])))) - 1
        c = splited[5+5*i]
        boxes.append([xmin, ymin, xmax, ymax])
        labels.append(int(c))
    return fname, boxes, labels


def get_pred_boxes(img, img_size, net, cls_id=0):  # 0: void
    x = img.resize((img_size, img_size))
    x = transform(x)
    x = Variable(x, volatile=True).cuda()
    loc_preds, cls_preds = net(x.unsqueeze(0))
    box_coder = SSDBoxCoder(net)
    boxes, labels, scores = box_coder.decode(
        loc_preds.data.squeeze().cpu(),
        F.softmax(cls_preds.squeeze(), dim=1).data.cpu())
    boxes = [box for i, box in enumerate(boxes) if labels[i] == cls_id]
    return boxes


def draw_preds_and_save(img, model_inp_size, boxes, out_dir, fname, test_code):
    h0, w0 = img.shape[:2]
    h1, w1 = model_inp_size, model_inp_size
    x_trans = w0/w1
    y_trans = h0/h1
    for x1, y1, x2, y2 in boxes:
        x1 = np.int64(np.round(x1 * x_trans))
        x2 = np.int64(np.round(x2 * x_trans))
        y1 = np.int64(np.round(y1 * y_trans))
        y2 = np.int64(np.round(y2 * y_trans))
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
    fpath = osp.join(out_dir, fname)
    cv2.imwrite(fpath, img)
    if test_code:
        os.remove(fpath)


parser = argparse.ArgumentParser(description='Draws bounding box predictions')
parser.add_argument('--input', default='../../data/voids/', type=str, help="Directory to read images from")  # noqa
parser.add_argument('--output', default='outputs', type=str, help="Directory to write drawing to")  # noqa

parser.add_argument('--checkpoint', default='checkpoints/2018-02-16_first-model.pth', type=str, help='Checkpoint path')  # noqa
parser.add_argument('--video-id', default=-1, type=int, choices=[-1, 0, 1])  # noqa
parser.add_argument('--draw-ground-truth', action='store_true')  # noqa
parser.add_argument('--gpu', default='0', type=int, help='GPU ID (nvidia-smi)')  # noqa
parser.add_argument('--test-code', action='store_true', help='Use a small sample of the data.')  # noqa
args = parser.parse_args()

OUTPUT_DIR_SUFFIX = ''  # Make this whatever you'd like
IMG_SIZE = 512  # TODO: Use orginal dimensions of each image
LABEL_DIR = "labels"
CLS_ID = 0  # void

video_name = videoid2videoname(args.video_id)
use_gt = "_gt" if args.draw_ground_truth else ''
suffix = "_" + OUTPUT_DIR_SUFFIX if OUTPUT_DIR_SUFFIX else ''
in_dir = osp.join(args.input, video_name)
out_dir = osp.join(args.output, video_name + use_gt + suffix)
if in_dir != "/inputs":  # i.e. if not Docker
    print("in_dir:", in_dir)
    print("out_dir:", out_dir if out_dir[-1] != '/' else out_dir[:-1])
os.makedirs(out_dir, exist_ok=True)

print('Loading model..')
net = FPNSSD512_2()
ckpt = torch.load(args.checkpoint)
net.load_state_dict(ckpt['net'])

with torch.cuda.device(args.gpu):
    net.cuda()
    net.eval()

    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
        ])

    if args.draw_ground_truth:
        ground_truth_txt = osp.join(LABEL_DIR, video_name + ".txt")
        with open(ground_truth_txt) as f:
            ground_truth_lines = f.readlines()
        n = 10 if args.test_code else len(ground_truth_lines)
        tqdm_lines = tqdm(ground_truth_lines[:n], ncols=80)
        for line in tqdm_lines:
            fname, gt_boxes, gt_labels = get_ground_truth(line)
            gt_boxes = [box for i, box in enumerate(gt_boxes)
                        if gt_labels[i] == CLS_ID]
            tqdm_lines.set_postfix(fname=fname)
            img = Image.open(osp.join(in_dir, fname))
            pred_boxes = get_pred_boxes(img, IMG_SIZE, net, cls_id=CLS_ID)
            img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            for x1, y1, x2, y2 in gt_boxes:
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
            draw_preds_and_save(img, IMG_SIZE, pred_boxes, out_dir, fname,
                                args.test_code)
    else:
        fpaths = glob(in_dir + "/*.jpg")
        fpaths.sort()
        n = 10 if args.test_code else len(fpaths)
        tqdm_fpaths = tqdm(fpaths[:n], ncols=80)
        for fpath in tqdm_fpaths:
            fname = fpath.split('/')[-1]
            tqdm_fpaths.set_postfix(fname=fname)
            img = Image.open(osp.join(in_dir, fname))
            pred_boxes = get_pred_boxes(img, IMG_SIZE, net, cls_id=CLS_ID)
            img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            draw_preds_and_save(img, IMG_SIZE, pred_boxes, out_dir, fname,
                                args.test_code)
