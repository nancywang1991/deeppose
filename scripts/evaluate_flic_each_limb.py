#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function
import sys
sys.path.append('tests')
import glob
import re
import os
import imp
import argparse
import numpy as np
import cv2 as cv
from chainer import cuda, serializers, Variable
from transform import Transform
from test_flic_dataset import draw_joints
import pdb
import glob
import subprocess
import cPickle as pickle

def load_model(args):
    model_fn = os.path.basename(args.model)
    model_name = model_fn.split('.')[0]
    model = imp.load_source(model_name, args.model).model
    serializers.load_hdf5(args.param, model)
    model.train = False

    return model


def load_data(trans, args, x):
    c = args.channel
    s = args.size
    d = args.joint_num * 2

    # data augmentation
    input_data = np.zeros((len(x), c, s, s))
    label = np.zeros((len(x), d))

    for i, line in enumerate(x):
        d, t = trans.transform(line.split(','), args.datadir,
                               args.fname_index, args.joint_index)
        input_data[i] = d.transpose((2, 0, 1))
        label[i] = t

    return input_data, label

def load_video(trans, args):
    c = args.channel
    s = args.size
    d = args.joint_num * 2

    subprocess.call(["mkdir", "tmp"])
    subprocess.call(["ffmpeg", "-i", args.datadir + "/" + args.vidfile,
                     "-r", "30", "-f", "image2", "tmp/%d.png"])

    x = glob.glob("tmp/*.png")

    # data augmentation
    input_data = np.zeros((len(x), c, s, s))
    label = np.zeros((len(x), d))

    for i, line in enumerate(x):
        d = trans.transform_vid_frame("tmp", i+1)
        input_data[i] = d.transpose((2, 0, 1))

    return input_data, label

def save_vid_res(pred, out_dir, fname):
    subprocess.call(["avconv", "-r", "30", "-i", "tmp/%d.png",
                     "-b:v", "1000k", out_dir + "/" + fname + ".avi"])
    subprocess.call(["rm", "-r", "tmp"])
    pickle.dump(pred, open(out_dir + "/" + fname + ".p","wb"))
    
def create_tiled_image(perm, out_dir, result_dir, epoch, suffix, N=25):
    fnames = np.array(sorted(glob.glob('%s/*%s.jpg' % (out_dir, suffix))))
    tile_fnames = fnames[perm[:N]]

    h, w, pad = 220, 220, 2
    side = int(np.ceil(np.sqrt(len(tile_fnames))))
    canvas = np.zeros((side * h + pad * (side + 1),
                      side * w + pad * (side + 1), 3))

    for i, fname in enumerate(tile_fnames):
        img = cv.imread(fname)
        x = w * (i % side) + pad * (i % side + 1)
        y = h * (i // side) + pad * (i // side + 1)
        canvas[y:y + h, x:x + w, :] = img

    if args.resize > 0:
        canvas = cv.resize(canvas, (args.resize, args.resize))
    cv.imwrite('%s/test_%d_tiled_%s.jpg' % (result_dir, epoch, suffix), canvas)


def test(args):
    # augmentation setting
    trans = Transform(args)

    # test data
    test_fn = '%s/test_joints.csv' % args.datadir
    test_dl = np.array([l.strip() for l in open(test_fn).readlines()])

    # load model
    if args.gpu >= 0:
        cuda.get_device(args.gpu).use()
    model = load_model(args)
    if args.gpu >= 0:
        model.to_gpu()
    else:
        model.to_cpu()

    # create output dir
    epoch = int(re.search('epoch-([0-9]+)', args.param).groups()[0])
    result_dir = os.path.dirname(args.param)
    out_dir = '%s/test_%d' % (result_dir, epoch)
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    out_log = '%s.log' % out_dir
    fp = open(out_log, 'w')

    mean_error = np.zeros(7)
    N = len(test_dl)
    for i in range(0, N, args.batchsize):
        lines = test_dl[i:i + args.batchsize]
        input_data, labels = load_data(trans, args, lines)

        if args.gpu >= 0:
            input_data = cuda.to_gpu(input_data.astype(np.float32))
            labels = cuda.to_gpu(labels.astype(np.float32))

        x = Variable(input_data, volatile=True)
        t = Variable(labels, volatile=True)
        model(x, t)

        if args.gpu >= 0:
            preds = cuda.to_cpu(model.pred.data)
            input_data = cuda.to_cpu(input_data)
            labels = cuda.to_cpu(labels)

        for n, line in enumerate(lines):
            img_fn = line.split(',')[args.fname_index]
            img = input_data[n].transpose((1, 2, 0))
            pred = preds[n]
            img_pred, pred = trans.revert(img, pred)

            # turn label data into image coordinates
            label = labels[n]
            img_label, label = trans.revert(img, label)

            # calc mean_error
            error = np.linalg.norm(pred - label, axis=1)
            mean_error += error

            # create pred, label tuples
            img_pred = np.array(img_pred.copy())
            img_label = np.array(img_label.copy())
            pred = [tuple(p) for p in pred]
            label = [tuple(p) for p in label]

            # all limbs
            img_label = draw_joints(
                img_label, label, args.draw_limb, args.text_scale)
            img_pred = draw_joints(
                img_pred, pred, args.draw_limb, args.text_scale)

            msg = '{:5}/{:5} {}\tshoulderl:{}\tshoulderr:{}\tnose:{}\telbowl:{}\telbowr:{}\twristl:{}\twristr:{}'.format(
                i + n, N, img_fn, error[2],error[4],error[3],error[1],error[5],error[0],error[6])
            print(msg, file=fp)
            print(msg)
            fn, ext = os.path.splitext(img_fn.split('/')[-1])
            tr_fn = '%s/%d-%d_%s_pred%s' % (out_dir, i, n, fn, ext)
            la_fn = '%s/%d-%d_%s_label%s' % (out_dir, i, n, fn, ext)
            cv.imwrite(tr_fn, img_pred)
            cv.imwrite(la_fn, img_label)


def video_test(args):
    # augmentation setting
    trans = Transform(args)

    # test data
    test_fn = args.datadir
    #test_dl = np.array([l.strip() for l in open(test_fn).readlines()])

    # load model
    if args.gpu >= 0:
        cuda.get_device(args.gpu).use()
    model = load_model(args)
    if args.gpu >= 0:
        model.to_gpu()
    else:
        model.to_cpu()

    # create output dir
    epoch = int(re.search('epoch-([0-9]+)', args.param).groups()[0])
    result_dir = os.path.dirname(args.param)
    out_dir = '%s/test_%d' % (result_dir, epoch)
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    out_log = '%s.log' % out_dir
    fp = open(out_log, 'w')

    input_data_all, labels_all = load_video(trans, args)

    preds_all =[]
    for i in range(0, len(input_data_all), args.batchsize):
        if args.gpu >= 0:
            input_data = cuda.to_gpu(input_data_all[i:i+args.batchsize].astype(np.float32))
            labels = cuda.to_gpu(labels_all[i:i+args.batchsize].astype(np.float32))

        x = Variable(input_data, volatile=True)
        t = Variable(labels, volatile=True)
        model(x, t)

        if args.gpu >= 0:
            preds = cuda.to_cpu(model.pred.data)
            input_data = cuda.to_cpu(input_data)
            labels = cuda.to_cpu(labels)
        
        
        for n in xrange(len(input_data)):
            
            img = input_data[n].transpose((1, 2, 0))
            pred = preds[n]
            img_pred, pred = trans.revert(img, pred)

            # turn label data into image coordinates
            label = labels[n]
            img_label, label = trans.revert(img, label)

                
            # create pred, label tuples
            img_pred = np.array(img_pred.copy())
                
            pred = [tuple(p) for p in pred]

            # all limbs
            img_pred = draw_joints(
                    img_pred, pred, args.draw_limb, args.text_scale)
            
            tr_fn = 'tmp/%d.png' % (i+n+1)
            cv.imwrite(tr_fn, img_pred)
            preds_all.append(pred)
    save_vid_res(preds_all, out_dir, args.vidfile.split(".")[0])
            
def tile(args):
    # create output dir
    epoch = int(re.search('epoch-([0-9]+)', args.param).groups()[0])
    result_dir = os.path.dirname(args.param)
    out_dir = '%s/test_%d' % (result_dir, epoch)
    if not os.path.exists(out_dir):
        raise Exception('%s is not exist' % out_dir)

    # save tiled image of randomly chosen results and labels
    n_img = len(glob.glob('%s/*pred*' % (out_dir)))
    perm = np.random.permutation(n_img)
    create_tiled_image(perm, out_dir, result_dir, epoch, 'pred', args.n_imgs)
    create_tiled_image(perm, out_dir, result_dir, epoch, 'label', args.n_imgs)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=str,
                        help='model definition file in models dir')
    parser.add_argument('--param', type=str,
                        help='trained parameters file in result dir')
    parser.add_argument('--batchsize', type=int, default=128)
    parser.add_argument('--gpu', type=int, default=0)
    parser.add_argument('--datadir', type=str, default='data/FLIC-full')
    parser.add_argument('--vidfile', type=str, default='')
    parser.add_argument('--mode', type=str, default='test',
                        choices=['test', 'tile', 'video'],
                        help='test or create tiled image')
    parser.add_argument('--n_imgs', type=int, default=9,
                        help='how many images will be tiled')
    parser.add_argument('--resize', type=int, default=-1,
                        help='resize the results of tiling')
    parser.add_argument('--seed', type=int, default=9,
                        help='random seed to select images to be tiled')
    parser.add_argument('--channel', type=int, default=3)

    parser.add_argument('--flip', type=int, default=0,
                        help='flip left and right for data augmentation')
    parser.add_argument('--cropping', type=int, default=1)
    parser.add_argument('--size', type=int, default=220,
                        help='resizing')
    parser.add_argument('--lcn', type=bool, default=True,
                        help='local contrast normalization for data'
                             ' augmentation')
    parser.add_argument('--crop_pad_inf', type=float, default=1.5,
                        help='random number infimum for padding size when'
                             ' cropping')
    parser.add_argument('--crop_pad_sup', type=float, default=1.5,
                        help='random number supremum for padding size when'
                             ' cropping')
    parser.add_argument('--shift', type=int, default=0,
                        help='slide an image when cropping')

    parser.add_argument('--joint_num', type=int, default=7)
    parser.add_argument('--fname_index', type=int, default=0,
                        help='the index of image file name in a csv line')
    parser.add_argument('--joint_index', type=int, default=1,
                        help='the start index of joint values in a csv line')
    parser.add_argument('--draw_limb', type=bool, default=True,
                        help='whether draw limb line to visualize')
    parser.add_argument('--text_scale', type=float, default=1.0,
                        help='text scale when drawing indices of joints')
    args = parser.parse_args()

    if args.mode == 'test':
        test(args)
    elif args.mode == 'tile':
        np.random.seed(args.seed)
        tile(args)
    elif args.mode == 'video':
	video_test(args)
