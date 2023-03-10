# -*- coding: utf-8 -*-
"""Copy of Semantic Parsing Stencil.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1mG_B09N9GsevrIGQPpcgtUvJ81nM0nxe

#[Github Link](https://github.com/YzyLmc/CS1460FinalProject)
#[Video Link](https://drive.google.com/file/d/1cMNvOt2pAYfNJmpH2vRA2m-VTWN90pY4/view?usp=sharing)
"""

# Setting seeds for reproducibility

import random
import torch
import numpy as np

random.seed(42)
torch.manual_seed(42)
np.random.seed(42)

"""# Data Pre-processing
### *I reversed the input sentences as the paper says*
"""

!pip install tqdm

# data from https://www.cs.utexas.edu/~ai-lab/pubs/cocktail-ecml-01.pdf
# and https://www.cs.utexas.edu/users/ml/nldata.html 

import regex as re
from nltk.stem import SnowballStemmer
from urllib.request import urlopen
from contextlib import closing
from sklearn.model_selection import train_test_split

ss = SnowballStemmer('english')

inputs = []
queries = []

with closing(urlopen('ftp://ftp.cs.utexas.edu/pub/mooney/nl-ilp-data/jobsystem/jobqueries640')) as r:
  for line in r.readlines():
    line = line.decode('utf-8')
    input, query = line.lower().split('],')

    # parse input. lowercase, stem with nltk, add <s>
    input = input[7:-2].split(',')
    input = [ss.stem(x) for x in input]
    inputs.append(input)

    # parse query 
    query = query.strip('.\n')
    # https://stackoverflow.com/questions/43092970/tokenize-by-using-regular-expressions-parenthesis
    query = re.findall(r"\w+(?:'\w+)?|[^\w\s]", query)
    query = ["<s>"] + query + ["</s>"]
    queries.append(query)

# do train test split of 500 training and 140 test instances
inputs_train, inputs_test, queries_train, queries_test = train_test_split(inputs, queries, test_size=140, random_state=8)

inputs_train = [ls[::-1] for ls in inputs_train] # reverse the input sentences
inputs_test = [ls[::-1] for ls in inputs_test]

inputs_train

from collections import Counter

input_vocab = Counter()
for l in inputs_train:
  input_vocab.update(l)

input_word2idx = {}
for w, c in input_vocab.items():
  if c >= 2:
    input_word2idx[w] = len(input_word2idx)
input_word2idx['<UNK>'] = len(input_word2idx)
input_word2idx['<PAD>'] = len(input_word2idx)
input_idx2word = {i:word for word,i in input_word2idx.items()}

input_vocab = list(input_word2idx.keys())

query_vocab = Counter()
for q in queries_train:
  query_vocab.update(q)
query_vocab['<UNK>'] = 0
query_vocab['<PAD>'] = 0
query_idx2word = {i:word for i, word in enumerate(query_vocab.keys())}
query_word2idx = {word:i for i, word in query_idx2word.items()}

inputs_train_tokens = [[input_word2idx.get(w, input_word2idx['<UNK>']) for w in l] for l in inputs_train]
inputs_test_tokens = [[input_word2idx.get(w, input_word2idx['<UNK>']) for w in l] for l in inputs_test]

queries_train_tokens = [[query_word2idx.get(w, query_word2idx['<UNK>']) for w in l] for l in queries_train]
queries_test_tokens = [[query_word2idx.get(w, query_word2idx['<UNK>']) for w in l] for l in queries_test]

def pad(input_seq, max_len, pad_token_idx):
  input_seq = input_seq[:max_len]
  padded_seq = input_seq + (max_len - len(input_seq)) * [pad_token_idx]
  return padded_seq

inputs_max_target_len = max([len(i) for i in inputs_train_tokens])
inputs_train_tokens = [pad(i, inputs_max_target_len, input_word2idx['<PAD>']) for i in inputs_train_tokens]
inputs_test_tokens = [pad(i, inputs_max_target_len, input_word2idx['<PAD>']) for i in inputs_test_tokens]

queries_max_target_len = int(max([len(i) for i in queries_train_tokens]) * 1.5)
queries_train_tokens = [pad(i, queries_max_target_len, query_word2idx['<PAD>']) for i in queries_train_tokens]
queries_test_tokens = [pad(i, queries_max_target_len, query_word2idx['<PAD>']) for i in queries_test_tokens]

"""# Data Loading"""

from torch.utils.data import Dataset, DataLoader, default_collate, default_convert

class JobsDataset(Dataset):
  def __init__(self, inputs, queries):
    self.inputs = inputs
    self.queries = queries

  def __len__(self):
      return len(self.inputs)

  def __getitem__(self, idx):
      return self.inputs[idx], self.queries[idx]

def build_datasets():
  jobs_train = JobsDataset(inputs=inputs_train_tokens, queries=queries_train_tokens)
  jobs_test = JobsDataset(inputs=inputs_test_tokens, queries=queries_test_tokens)
  return jobs_train, jobs_test

def collate(batch):
  src, tgt = default_collate(batch)
  #src, tgt = default_convert(batch)
  return torch.stack(src), torch.stack(tgt)

def build_dataloaders(dataset_train, dataset_test, train_batch_size, test_batch_size):
  dataloader_train = DataLoader(dataset_train, batch_size=train_batch_size, shuffle=True, collate_fn=collate)
  dataloader_test = DataLoader(dataset_test, batch_size=test_batch_size, shuffle=False, collate_fn=collate)
  return dataloader_train, dataloader_test

"""# Todo: Define model"""

import torch.nn.functional as F
from torch import nn
from torch.autograd import Variable

class EncoderLSTM(nn.Module):

  def __init__(self, vocab_size, embedding_size, hidden_size, padding_idx, dropout_ratio):
    super(EncoderLSTM, self).__init__()
    self.embedding_size = embedding_size
    self.hidden_size = hidden_size
    self.drop = nn.Dropout(p=dropout_ratio)

    self.embedding = nn.Embedding(vocab_size, embedding_size, padding_idx)
    self.lstm = nn.LSTM(embedding_size, hidden_size, batch_first=True)
    
  def forward(self, inputs):
      batch_size = inputs.size(0)
      embeds = self.embedding(inputs)  # (batch, seq_len, hidden_size)

      ctx, (enc_h_t, enc_c_t) = self.lstm(embeds)

      # h_t and c_t are h_0 and c_0 of the decoder
      h_t = enc_h_t[-1]
      h_t = self.drop(h_t) # dropout hidden vector
      c_t = enc_c_t[-1]  # (batch, hidden_size)

      return ctx, h_t, c_t
    
class AttnDecoderLSTM(nn.Module):
  def __init__(self, vocab_size, embedding_size, hidden_size, padding_idx, dropout_ratio):
    super(AttnDecoderLSTM, self).__init__()
    self.vocab_size = vocab_size
    self.embedding_size = embedding_size
    self.hidden_size = hidden_size
    self.drop = nn.Dropout(p=dropout_ratio)

    self.sm_attn = nn.Softmax(dim=1)
    self.embedding = nn.Embedding(vocab_size, embedding_size, padding_idx)
    self.lstm = nn.LSTMCell(embedding_size, hidden_size) # use LSTMCell here to decode step by step
    self.tanh = nn.Tanh()
    self.ht2hatt = nn.Linear(hidden_size, hidden_size)
    self.ct2hatt = nn.Linear(hidden_size, hidden_size)
    self.hatt2logit = nn.Linear(hidden_size, vocab_size)

  def attn(self, h, context, mask=None):
    '''Propagate h through the network.
    h: batch x dim
    context: batch x seq_len x dim
    mask: batch x seq_len indices to be masked
    '''
    target = h.unsqueeze(2)  # batch x dim x 1
    # Get attention
    attn = torch.bmm(context, target).squeeze(2)  # batch x seq_len
    if mask is not None:
        # -Inf masking prior to the softmax
        attn.data.masked_fill_(mask.bool(), -float('inf'))
    attn = self.sm_attn(attn)
    attn3 = attn.view(attn.size(0), 1, attn.size(1))  # batch x 1 x seq_len
    weighted_context = torch.bmm(attn3, context).squeeze(1)  # batch x dim

    return weighted_context, attn

  def forward(self, y_prev, h_0, c_0, ctx,
            ctx_mask=None):
    ''' Takes a single step in the decoder LSTM.
    y_prev: batch x embedding_size
    h_0: batch x hidden_size
    c_0: batch x hidden_size
    ctx: batch x seq_len x dim
    ctx_mask: batch x seq_len - indices to be masked
    '''
    
    embeds = self.embedding(y_prev)
    h_1, c_1 = self.lstm(embeds, (h_0, c_0))
    c_t, attn = self.attn(h_1, ctx, mask=ctx_mask)
    h_att = self.tanh(self.ht2hatt(h_1) + self.ct2hatt(c_t))
    h_att = self.drop(h_att)
    logit = self.hatt2logit(h_att)

    return h_1, c_1, logit

class Seq2SeqModel():
  def __init__(self, encoder, decoder, max_length):
    self.encoder = encoder
    self.decoder = decoder
    self.max_length = max_length

  def generate(self, inputs, labels, masks, device, test=False):
    '''
    Generate function for translating input natural language to queries.
    inputs: batch X seq_length(input)
    labels: batch X seq_length(query)
    masks: batch X seq_length(input)
    '''
    batch_size = len(inputs)
    ended = np.array([False] * batch_size)
    y_t = Variable(torch.from_numpy(np.full((batch_size,), QUERY_SOS_INDEX, dtype='int64')).long(),
                                requires_grad=False).to(device)
    
    ctx, h_t, c_t = self.encoder(inputs) # encoding inputs

    loss = 0
    instr_pred = []

    for t in range(self.max_length):
      h_t, c_t, logit = self.decoder(y_t, h_t, c_t, ctx,
            ctx_mask=masks)
      target = labels[:,t].contiguous()
      probs = F.softmax(logit,dim=1)

      # update loss
      log_probs = F.log_softmax(logit, dim=1)
      loss += F.nll_loss(log_probs, target, ignore_index=QUERY_PAD_INDEX)

      if test:
        _,y_t = logit.max(1)        # student forcing when evaluation
        y_t = y_t.detach()
        instr_pred.append(y_t.clone().unsqueeze(0))
      else:
        y_t = target                # teacher forcing when training

      # terminate the loop if all queries end
      for i in range(len(y_t)):
        word_idx = y_t[i].item()
        if word_idx == QUERY_EOS_INDEX:
          ended[i] = True
      if ended.all(): break

    if test:
      instr_pred = torch.cat(instr_pred, 0)
      instr_pred = instr_pred.transpose(0, 1).int() # batch X seq_length
    
    return loss, instr_pred

def create_model(embedding_size, hidden_size, dropout_ratio, device):
  max_length = queries_max_target_len - 1 # no <s>
  train_vocab_size = len(list(input_idx2word.keys()))
  query_vocab_size = len(list(query_idx2word.keys()))

  encoder = EncoderLSTM(train_vocab_size, embedding_size, hidden_size, INPUT_PAD_INDEX, dropout_ratio).to(device)
  decoder = AttnDecoderLSTM(query_vocab_size, embedding_size, hidden_size, QUERY_PAD_INDEX, dropout_ratio).to(device)
  seq2seq = Seq2SeqModel(encoder, decoder, max_length)

  return seq2seq

"""# Todo: Training and testing loops"""

QUERY_SOS_INDEX = query_word2idx['<s>']
QUERY_EOS_INDEX = query_word2idx['</s>']
QUERY_PAD_INDEX = query_word2idx['<PAD>']
INPUT_PAD_INDEX = input_word2idx['<PAD>']

def train(model, encoder_optimizer, decoder_optimizer, train_dataloader, test_dataloader, num_epochs, device="cuda"):
  batch_size = train_dataloader.batch_size
  for epoch in range(num_epochs):
    model.encoder.train()
    model.decoder.train()

    print(f"Epoch {epoch + 1} training:")
    progress_bar = tqdm(range(len(train_dataloader)))

    total_loss = 0
    for i, batch in enumerate(train_dataloader):
      
      # get inputs and labels from batch, and transpose them
      inputs = torch.transpose(batch[0].clone().detach().to(device), 0, 1)
      labels = torch.transpose(batch[1][1:].clone().detach().to(device), 0, 1) # no <s>
      # consruct masks from inputs
      masks = torch.zeros_like(inputs)
      masks[inputs==INPUT_PAD_INDEX] = 1

      loss, _ = model.generate(inputs, labels, masks, device, test=False)
      loss.backward()
      total_loss += loss.clone().detach()
      
      encoder_optimizer.step()
      decoder_optimizer.step()

      encoder_optimizer.zero_grad()
      decoder_optimizer.zero_grad()
      progress_bar.update(1)

    print(f"Epoch {epoch+1} average training loss:{total_loss/(batch_size*i)}")

    print("Running validation:")

    test_score = evaluate(model, test_dataloader, device=device)
    print(f"Epoch {epoch+1} validation: accuracy={test_score}")

def evaluate(model, dataloader, device="cuda"):
  model.encoder.eval()
  model.decoder.eval()

  progress_bar = tqdm(range(len(dataloader)))
  correct = 0
  total = 0
  with torch.no_grad():
    for batch in dataloader:
      inputs = torch.transpose(batch[0].clone().detach().to(device), 1, 0)
      labels = torch.transpose(batch[1][1:].clone().detach().to(device), 1, 0)
      masks = torch.zeros_like(inputs)
      masks[inputs!=INPUT_PAD_INDEX] = 1

      loss, instr_output = model.generate(inputs, labels, masks, device, test=True)
      
      

      for i in range(len(instr_output)):
        for j in range(len(instr_output[0])):
          if instr_output[i,j] == QUERY_EOS_INDEX:
            instr_output[i,j+1:] = QUERY_PAD_INDEX

      # calculate num of correct tokens and total tokens

      total_tokens = torch.zeros_like(labels)
      total_tokens[labels!=QUERY_PAD_INDEX] = 1
      total_tokens[labels==QUERY_EOS_INDEX] = 0 # no <s> or </s>
      total_tokens[labels==QUERY_SOS_INDEX] = 0      

      #total_tokens = torch.zeros_like(instr_output)
      #total_tokens[instr_output!=QUERY_PAD_INDEX] = 1
      #total_tokens[instr_output==QUERY_EOS_INDEX] = 0 # no <s> or </s>
      #total_tokens[instr_output==QUERY_SOS_INDEX] = 0
      total += torch.sum(total_tokens)

      correct_tokens = torch.zeros_like(instr_output)
      labels = labels[:,:len(instr_output[0])]
      correct_tokens[instr_output==labels] = 1
      correct_tokens[labels==QUERY_PAD_INDEX] = 0

      correct += torch.sum(correct_tokens)

  # visualize 5 examples
  input_first5 = inputs.detach().tolist()[:5]
  query_first5 = instr_output.detach().tolist()[:5]

  input_first5 = [[input_idx2word[i] for i in exp] for exp in input_first5]
  query_first5 = [[query_idx2word[i] for i in exp] for exp in query_first5]
  print('Visualizing 5 examples of translation...')
  for i in range(5):
    print(input_first5[i], query_first5[i])

  return correct/total

"""# Run this!

Your outputs should look something like this (not exactly the same numbers, just in a similar ballpark and format).

```
Epoch: 1, Train loss: 4.590
Epoch: 2, Train loss: 1.871
Epoch: 3, Train loss: 1.424
...
Test Accuracy: 0.5195115804672241
```


"""

from tqdm.auto import tqdm

def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    jobs_train, jobs_test = build_datasets()
    dataloader_train, dataloader_test = build_dataloaders(jobs_train, jobs_test, train_batch_size=60, test_batch_size=20)
    model = create_model(350, 350, 0.25, device)
    en_optim = torch.optim.AdamW(model.encoder.parameters(), lr=5e-4)
    de_optim = torch.optim.AdamW(model.decoder.parameters(), lr=5e-4)
    train(model, en_optim, de_optim, dataloader_train, dataloader_test, num_epochs=20, device=device)
    test_accuracy = evaluate(model, dataloader_test, device=device)
    print(f'Test Accuracy: {test_accuracy}')


main()

"""## The highest accuracy is ahcieved at epoch #15, and euqals to 52.40%. This result is reproducible on Colab with setting runtime type = GPU"""