import string
import torch
import torch.nn as nn
from torch.nn.utils.rnn import pad_sequence
from torchmetrics import ConfusionMatrix
import pytorch_lightning as pl
from pytorch_lightning.metrics import functional as FM
from leven import levenshtein

from settings import *
from phonemes import Phoneme
from models.gru import GRUModel
from models.ligru import LiGRUModel
from models.phoneme_boundary_detector import PhonemeBoundaryDetector
from dataset.disk_dataset import DiskDataset


class PhonemeClassifier(pl.LightningModule):

    def __init__(self, batch_size, lr, lr_patience, lr_reduce_factor, steps_per_epoch):
        super().__init__()
        self.batch_size = batch_size
        self.lr = lr
        self.lr_patience = lr_patience
        self.lr_reduce_factor = lr_reduce_factor
        self.steps_per_epoch = steps_per_epoch
        self.lr_reduce_metric = 'val_loss'
        self.last_reduce_metric_val = float('inf')
        self.reduce_metric_too_high_count = 0
        self.num_classes = Phoneme.folded_phoneme_count()
        self.model = GRUModel(output_size=self.num_classes)
        # self.criterion = nn.CTCLoss(reduction='none')#weight=Phoneme.folded_phoneme_weights)
        self.criterion = nn.CrossEntropyLoss()
        self.optimizer = torch.optim.AdamW(
            self.parameters(), lr=self.lr)
        self.confmatMetric = ConfusionMatrix(num_classes=Phoneme.folded_group_phoneme_count())

    def training_step(self, batch, step):
        loss = self.calculate_metrics(batch, mode='train')
        self.update_lr(step)
        self.log('train_loss', loss)
        self.log('lr', self.optimizer.param_groups[0]['lr'], prog_bar=True)
        return loss

    def remove_silences(self, preds, labels):
        sil_idx = Phoneme.folded_phoneme_list.index('sil')
        non_glottal_indices = torch.nonzero(labels.ne(sil_idx))
        preds = preds[non_glottal_indices]
        labels = labels[non_glottal_indices]
        return preds, labels

    def validation_step(self, batch, _):
        loss, acc, per = self.calculate_metrics(batch, mode='val')
        metrics = {'val_loss': loss, 'val_FER': 1-acc, 'val_PER': per}
        self.log_dict(metrics, prog_bar=True)
        return metrics

    def validation_epoch_end(self, val_step_outputs): # plateau scheduler
        reduce_metric_val = sum([output[self.lr_reduce_metric] for output in val_step_outputs])/len(val_step_outputs)
        if reduce_metric_val > self.last_reduce_metric_val * 0.9999:
            self.reduce_metric_too_high_count += 1
        if self.reduce_metric_too_high_count > self.lr_patience:
            self.lr *= self.lr_reduce_factor
            self.reduce_metric_too_high_count=0
        self.last_reduce_metric_val = reduce_metric_val

    def test_step(self, batch, _):
        loss, acc, per = self.calculate_metrics(batch, mode='test')
        metrics = {'test_loss': loss, 'test_FER': 1-acc, 'test_PER': per}
        self.log_dict(metrics, prog_bar=True)

    def configure_optimizers(self):
        return self.optimizer

    def update_lr(self, step): # one-cycle lr per epoch
        half_steps = self.steps_per_epoch // 2
        min_lr = 1/10 * self.lr
        if step < half_steps:
            c = step / half_steps
            lr = min_lr + c * (self.lr - min_lr)
        else:
            c = (step - half_steps) / half_steps
            lr = self.lr - c * (self.lr - min_lr)
        self.optimizer.param_groups[0]['lr'] = lr

    def calculate_metrics(self, batch, mode):
        (fbank, lengths), labels = batch
        labels = self.remove_padding(labels, lengths)
        outputs = self.model(fbank, lengths)
        outputs = self.remove_padding(outputs, lengths)
        # probs = (outputs).transpose(0, 1).log_softmax(2)
        # print('--')
        # print("x.shape", probs.shape)
        # print("y.shape", labels.shape)
        # print("lengths", lengths)
        # labels = labels.type(torch.int32)
        # lengths = lengths.type(torch.int32)
        # lossv = self.criterion(probs, labels, lengths, lengths)
        # print(lossv)
        # loss = torch.mean(lossv)
        # print(loss)
        # if not torch.isfinite(loss):
        #     exit()

        loss = self.criterion(torch.cat(outputs), torch.cat(labels))
        if mode == 'train':
            return loss

        preds = [torch.argmax(output, dim=1) for output in outputs]
        preds_folded = self.foldGroupIndices(preds, lengths)
        labels_folded = self.foldGroupIndices(labels, lengths)
        per_value = self.calculate_per(preds_folded, labels_folded, lengths)
        preds_folded = torch.cat(preds_folded)
        labels_folded = torch.cat(labels_folded)
        acc = FM.accuracy(preds_folded, labels_folded)
        
        if mode == 'val':
            return loss, acc, per_value

        self.confmatMetric(preds_folded, labels_folded)
        return loss, acc, per_value
    
    def calculate_per(self, preds, labels, lengths):
        pn_labels_pred = self.get_phoneme_labels(preds, lengths)
        pn_labels_correct = self.get_phoneme_labels(labels, lengths)
        batch_size = lengths.size(0)
        distances = torch.zeros(batch_size)
        for i in range(batch_size):
            distances[i] = levenshtein(
                self.intarray_to_unique_string(pn_labels_pred[i]),
                self.intarray_to_unique_string(pn_labels_correct[i])) / len(pn_labels_correct[i])
        return torch.mean(distances)
    
    def remove_padding(self, tensor, lengths):
        return [tensor[i][:lengths[i]] for i in range(tensor.size(0))]

    def get_phoneme_labels(self, segment_labels, lengths, boundaries=None):
        pn_labels = []
        for i in range(lengths.size(0)):
            pn_labels.append([segment_labels[i][0]])
            pn_labels[i].extend(segment_labels[i][j]
                             for j in range(lengths[i])
                             if segment_labels[i][j] != segment_labels[i][j-1])
        return pn_labels
    
    def intarray_to_unique_string(self, intarray):
        return ''.join([chr(65+i) for i in intarray])

    def foldGroupIndices(self, indizes, lengths):
        for i in range(lengths.size(0)):
            for j in range(lengths[i]):
                symbol = Phoneme.folded_phoneme_list[indizes[i][j]]
                indizes[i][j] = Phoneme.folded_group_phoneme_list.index(Phoneme.symbol_to_folded_group.get(symbol, symbol))
        return indizes

    # hide v_num in progres bar
    def get_progress_bar_dict(self):
        tqdm_dict = super().get_progress_bar_dict()
        if 'v_num' in tqdm_dict:
            del tqdm_dict['v_num']
        return tqdm_dict