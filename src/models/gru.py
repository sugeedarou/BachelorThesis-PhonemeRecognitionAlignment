import torch
import torch.nn as nn

from settings import *


class GRUModel(nn.Module):
    def __init__(self, output_size):
        super().__init__()
        self.output_size = output_size
        self.rnn = nn.GRU(input_size=N_MELS,
                           hidden_size=512,
                           num_layers=3,
                           batch_first=True, bidirectional=True)
        self.fc = nn.Linear(self.rnn.hidden_size*2, self.output_size)

    def forward(self, batch, lengths, device):
        h0 = torch.zeros(self.rnn.num_layers*2, batch.size(0),
                         self.rnn.hidden_size, device=device)
        out, _ = self.rnn(batch, h0)
        out = self.fc(out)
        predictions = []
        for i in range(batch.size(0)):
            predictions.append(out[i][:lengths[i]])
        return predictions