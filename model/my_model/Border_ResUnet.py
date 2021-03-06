import torch
import torch.nn as nn
import torch.nn.functional as F
from model.segbase import SegBaseModel
from model.model_utils import init_weights, _FCNHead
from .blocks import *



class border_branch(nn.Module):
    def __init__(self, channel_1, channel_2):
        super().__init__()
        self.conv1 = nn.Sequential(
            nn.Conv2d(channel_1, channel_1, kernel_size=1),
            nn.BatchNorm2d(channel_1),
            nn.ReLU(True),
            nn.Conv2d(channel_1, channel_1, kernel_size=3, padding=1),
            nn.BatchNorm2d(channel_1),
            nn.ReLU(True)
        )
        self.conv2 = nn.Sequential(
            nn.Conv2d(channel_2, channel_2, kernel_size=1),
            nn.BatchNorm2d(channel_2),
            nn.ReLU(True),
            nn.Conv2d(channel_2, channel_2, kernel_size=3, padding=1),
            nn.BatchNorm2d(channel_2),
            nn.ReLU(True)
        )
        self.conv_out = nn.Conv2d(channel_1+channel_2, 2, kernel_size=1)

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                torch.nn.init.kaiming_normal_(m.weight)
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()

    def forward(self, x1, x2):
        x2 = F.interpolate(x2, size=x1.size()[-2:], mode="bilinear", align_corners=True)

        x1 = self.conv1(x1)
        x2 = self.conv2(x2)
        c = torch.cat((x1, x2), dim=1)
        out = self.conv_out(c)

        return {"main_out": out,
                "c": c}





class Border_ResUnet(SegBaseModel):

    def __init__(self, n_class, backbone='resnet34', aux=False, pretrained_base=False, dilated=True, deep_stem=False, **kwargs):
        super(Border_ResUnet, self).__init__(backbone, pretrained_base=pretrained_base, dilated=dilated, deep_stem=deep_stem, **kwargs)
        self.aux = aux
        self.dilated = dilated
        channels = self.base_channel
        if deep_stem or backbone == 'resnest101':
            conv1_channel = 128
        else:
            conv1_channel = 64

        if dilated:
            self.donv_up3 = decoder_block(channels[0]+channels[3], channels[0])
            self.donv_up4 = decoder_block(channels[0]+conv1_channel, channels[0])
        else:
            self.donv_up1 = decoder_block(channels[2] + channels[3], channels[2])
            self.donv_up2 = decoder_block(channels[1] + channels[2], channels[1])
            self.donv_up3 = decoder_block(channels[0] + channels[1], channels[0])
            self.donv_up4 = decoder_block(channels[0] + conv1_channel, channels[0])

        self.border_branch = border_branch(conv1_channel, channels[0])

        self.out_conv = nn.Conv2d(channels[0]+conv1_channel+channels[0], n_class, kernel_size=1, bias=False)



    def forward(self, x):
        outputs = dict()
        size = x.size()[2:]
        x = self.backbone.conv1(x)
        x = self.backbone.bn1(x)
        c1 = self.backbone.relu(x)  # 1/2  64
        x = self.backbone.maxpool(c1)
        c2 = self.backbone.layer1(x)  # 1/4   64
        c3 = self.backbone.layer2(c2)  # 1/8   128
        c4 = self.backbone.layer3(c3)  # 1/16   256
        c5 = self.backbone.layer4(c4)  # 1/32   512

        border_out = self.border_branch(c1, c2)

        if self.dilated:
            x = self.donv_up3(c5, c2)
            x = self.donv_up4(x, c1)
        else:
            x = self.donv_up1(c5, c4)
            x = self.donv_up2(x, c3)
            x = self.donv_up3(x, c2)
            x = self.donv_up4(x, c1)

        x = torch.cat((x, border_out["c"]), dim=1)
        x = self.out_conv(x)

        x = F.interpolate(x, size, mode='bilinear', align_corners=True)  # 最后上采样
        edge = F.interpolate(border_out["main_out"], size, mode='bilinear', align_corners=True)  # 最后上采样

        outputs.update({"main_out": x})
        outputs.update({"edge": edge})
        return outputs












