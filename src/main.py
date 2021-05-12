import numpy as np
import warnings

from torch.optim import optimizer
# disable C++ extension warning
warnings.filterwarnings('ignore', 'torchaudio C\+\+', )
import torch.nn as nn
from torch.nn.utils.rnn import pad_sequence
from torch.utils.data import DataLoader, random_split
from torch.optim.lr_scheduler import ReduceLROnPlateau
import pytorch_lightning as pl
from pytorch_lightning.metrics import functional as FM

from settings import *
from dataset import TimitDataset
from phonemes import Phoneme
from model import Model


num_epochs = 30
batch_size = 16
initial_lr = 0.001


def collate_fn(batch):
    lengths = torch.tensor([item[0].size(0) for item in batch])
    frames = [item[0] for item in batch]
    frames = pad_sequence(frames, batch_first=True)
    labels = torch.cat([item[1] for item in batch])
    frame_data = (frames, lengths)
    return [frame_data, labels]

class TimitDataModule(pl.LightningDataModule):

    def setup(self, stage):
        train_val_data = TimitDataset(train=True)
        train_val_count = len(train_val_data)
        val_percentage = 0.2
        val_count = int(train_val_count * val_percentage)
        train_count = train_val_count - val_count

        self.train_ds, self.val_ds = random_split(train_val_data,
                                                 [train_count, val_count])
        self.test_ds = TimitDataset(train=False)

        self.ds_args = {'batch_size': batch_size,
                        'collate_fn': collate_fn,
                        'num_workers': 6,
                        'pin_memory': True}

    def train_dataloader(self):
        return DataLoader(dataset=self.train_ds,
                          shuffle=True,
                          **self.ds_args)

    def val_dataloader(self):
        return DataLoader(dataset=self.val_ds,
                          **self.ds_args)

    def test_dataloader(self):
        return DataLoader(dataset=self.test_ds,
                          **self.ds_args)
    

class PhonemeClassifier(pl.LightningModule):

    def __init__(self, batch_size, initial_lr):
        super().__init__()
        self.batch_size = batch_size
        self.initial_lr = initial_lr
        self.model = Model(output_size=Phoneme.phoneme_count())
        self.criterion = nn.CrossEntropyLoss()
        self.optimizer = torch.optim.Adam(self.parameters(), lr=self.initial_lr)
        self.lr_scheduler = ReduceLROnPlateau(self.optimizer, patience=1)

    def on_epoch_end(self):
        self.log('lr', self.optimizer.param_groups[0]['lr'], prog_bar=True)
    
    def training_step(self, batch, _):
        (specgrams, lengths), labels = batch

        outputs = self.model(specgrams, lengths)
        loss = self.criterion(outputs, labels)
        self.log('train_loss', loss)

        return loss

    def validation_step(self, batch, _):
        (specgrams, lengths), labels = batch
        specgrams = specgrams
        labels = labels

        outputs = self.model(specgrams, lengths)
        loss = self.criterion(outputs, labels)
        acc = FM.accuracy(torch.argmax(outputs, dim=1), labels)

        metrics = {'val_loss': loss, 'val_acc': acc}
        self.log_dict(metrics, prog_bar=True)
        return metrics

    def test_step(self, batch, batch_idx):
        metrics = self.validation_step(batch, batch_idx)
        metrics = {'test_loss': metrics['val_loss'], 'test_acc': metrics['val_acc']}
        self.log_dict(metrics, prog_bar=True)

    def configure_optimizers(self):
        lr_scheduler = {'scheduler': self.lr_scheduler,
                        'monitor': 'val_loss'}
        return [self.optimizer], [lr_scheduler]

    # hide v_num in progres bar
    def get_progress_bar_dict(self):
        tqdm_dict = super().get_progress_bar_dict()
        if 'v_num' in tqdm_dict:
            del tqdm_dict['v_num']
        return tqdm_dict


if __name__ == '__main__':
    dm = TimitDataModule()
    
    model = PhonemeClassifier(batch_size, initial_lr)
    trainer = pl.Trainer(gpus=1, max_epochs=num_epochs, precision=16)#, resume_from_checkpoint='lightning_logs/version_42/checkpoints/epoch=14-step=314.ckpt')

    trainer.fit(model, dm)
    trainer.test(datamodule=dm)