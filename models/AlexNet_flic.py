#!/usr/bin/env python
# -*- coding: utf-8 -*-

from chainer import Chain
import chainer.links as L
import chainer.functions as F


class AlexNet_flic(Chain):

    """
    AlexNet for FLIC dataset
    """

    def __init__(self):
        super(AlexNet_flic, self).__init__(
            conv1=L.Convolution2D(3, 96, 11, stride=4, pad=1),
            conv2=L.Convolution2D(96, 256, 5, stride=1, pad=2),
            conv3=L.Convolution2D(256, 384, 3, stride=1, pad=1),
            conv4=L.Convolution2D(384, 384, 3, stride=1, pad=1),
            conv5=L.Convolution2D(384, 256, 3, stride=1, pad=1),
            fc6=L.Linear(9216, 4096),
            fc7=L.Linear(4096, 4096),
            fc8=L.Linear(4096, 14)
        )
        self.train = True

    def __call__(self, x, t):
        h = F.relu(self.conv1(x))
        h = F.max_pooling_2d(h, 3, stride=2)
        h = F.local_response_normalization(h)

        h = F.relu(self.conv2(h))
        h = F.max_pooling_2d(h, 3, stride=2)
        h = F.local_response_normalization(h)

        h = F.relu(self.conv3(h))
        h = F.relu(self.conv4(h))
        h = F.relu(self.conv5(h))
        h = F.max_pooling_2d(h, 3, stride=2)

        h = F.dropout(F.relu(self.fc6(h)), train=self.train, ratio=0.6)
        h = F.dropout(F.relu(self.fc7(h)), train=self.train, ratio=0.6)

        self.pred = self.fc8(h)
        self.loss = F.mean_squared_error(self.pred, t)

        if self.train:
            return self.loss
        else:
            return self.pred

model = AlexNet_flic()
