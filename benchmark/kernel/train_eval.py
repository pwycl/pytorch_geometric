import sys
import random
import os.path as osp
import time

import tqdm
import torch
import torch.nn.functional as F
from torch import tensor
from torch.optim import Adam
from sklearn.model_selection import StratifiedKFold
from torch_geometric.data import DataLoader, DenseDataLoader as DenseLoader

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
file_name=osp.join('/kaggle/working',str(random.randrange(sys.maxsize))+'.txt')
# with open(file_name,'w') as f: #clear the output file
#     pass

def cross_validation_with_val_set(dataset,
                                  model,
                                  folds,
                                  epochs,
                                  batch_size,
                                  lr,
                                  lr_decay_factor,
                                  lr_decay_step_size,
                                  weight_decay,
                                  logger=None):

    val_losses, accs, durations = [], [], []

    acc_folds=0
    for fold, (train_idx, test_idx, val_idx) in enumerate(
            zip(*k_fold(dataset, folds))):
        train_dataset = dataset[train_idx]
        test_dataset = dataset[test_idx]
        val_dataset = dataset[val_idx]

        if 'adj' in train_dataset[0]:
            train_loader = DenseLoader(train_dataset, batch_size, shuffle=True)
            val_loader = DenseLoader(val_dataset, batch_size, shuffle=False)
            test_loader = DenseLoader(test_dataset, batch_size, shuffle=False)
        else:
            train_loader = DataLoader(train_dataset, batch_size, shuffle=True)
            val_loader = DataLoader(val_dataset, batch_size, shuffle=False)
            test_loader = DataLoader(test_dataset, batch_size, shuffle=False)

        model.to(device).reset_parameters()
        optimizer = Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

        if torch.cuda.is_available():
            torch.cuda.synchronize()

        t_start = time.perf_counter()

        if fold>1:
            break

        acc_folds+=1

        for epoch in range(1, epochs + 1):
            print('Train loss in Epoch: ',epoch)
            train_loss = train(model, optimizer, train_loader)
            print('Train acc in Epoch: ',epoch)
            train_acc=eval_acc(model,train_loader)
            print('Val in Epoch: ',epoch)
            v_loss,val_acc=eval_loss_acc(model, val_loader)
            val_losses.append(v_loss)
            print('Acc in Epoch: ',epoch)
            accs.append(eval_acc(model, test_loader))
            

            print('Train Loss: {:.4f}, Train Acc: {:.4f}, Val loss: {:.4f}, Val Acc: {:.4f}, Test Accuracy: {:.3f}'.
          format(train_loss, train_acc, val_losses[-1], val_acc, accs[-1]))

            eval_info = {
                'fold': fold,
                'epoch': epoch,
                'train_loss': train_loss,
                'val_loss': val_losses[-1],
                'test_acc': accs[-1],
            }

            if logger is not None:
                logger(eval_info)

            if epoch % lr_decay_step_size == 0:
                for param_group in optimizer.param_groups:
                    param_group['lr'] = lr_decay_factor * param_group['lr']

        if torch.cuda.is_available():
            torch.cuda.synchronize()

        t_end = time.perf_counter()
        durations.append(t_end - t_start)

    loss, acc, duration = tensor(val_losses), tensor(accs), tensor(durations)
    loss, acc = loss.view(-1, epochs), acc.view(-1, epochs)
    loss, argmin = loss.min(dim=1)
    acc = acc[torch.arange(acc_folds, dtype=torch.long), argmin]

    loss_mean = loss.mean().item()
    acc_mean = acc.mean().item()
    acc_std = acc.std().item()
    duration_mean = duration.mean().item()
    print('Val Loss: {:.4f}, Test Accuracy: {:.3f} ± {:.3f}, Duration: {:.3f}'.
          format(loss_mean, acc_mean, acc_std, duration_mean))

    with open(file_name,'a') as f:
        f.write('num_layers: {}, hidden: {}, Val Loss: {:.4f}, Test Accuracy: {:.3f} ± {:.3f}, Duration: {:.3f} \n'.
          format(model.num_layers, model.hidden, loss_mean, acc_mean, acc_std, duration_mean))

    return loss_mean, acc_mean, acc_std


def k_fold(dataset, folds):
    skf = StratifiedKFold(folds, shuffle=True, random_state=12345)

    test_indices, train_indices = [], []
    for _, idx in skf.split(torch.zeros(len(dataset)), dataset.data.y):
        test_indices.append(torch.from_numpy(idx))

    val_indices = [test_indices[i - 1] for i in range(folds)]

    for i in range(folds):
        train_mask = torch.ones(len(dataset), dtype=torch.uint8)
        train_mask[test_indices[i]] = 0
        train_mask[val_indices[i]] = 0
        train_indices.append(train_mask.nonzero().view(-1))

    return train_indices, test_indices, val_indices


def num_graphs(data):
    if data.batch is not None:
        return data.num_graphs
    else:
        return data.x.size(0)


def train(model, optimizer, loader):
    model.train()

    total_loss = 0
    for data in tqdm.tqdm(loader):
        optimizer.zero_grad()
        data = data.to(device)
        out = model(data)
        loss = F.nll_loss(out, data.y.view(-1))
        loss.backward()
        total_loss += loss.item() * num_graphs(data)
        optimizer.step()

    return total_loss / len(loader.dataset)


def eval_acc(model, loader):
    model.eval()

    correct = 0
    for data in tqdm.tqdm(loader):
        data = data.to(device)
        with torch.no_grad():
            pred = model(data).max(1)[1]
        correct += pred.eq(data.y.view(-1)).sum().item()
    return correct / len(loader.dataset)


def eval_loss(model, loader):
    model.eval()

    loss = 0
    for data in tqdm.tqdm(loader):
        data = data.to(device)
        with torch.no_grad():
            out = model(data)
        loss += F.nll_loss(out, data.y.view(-1), reduction='sum').item()
    return loss / len(loader.dataset)

def eval_loss_acc(model,loader):
    model.eval()

    loss = 0
    correct=0
    for data in tqdm.tqdm(loader):
        data=data.to(device)
        with torch.no_grad():
            out=model(data)
            pred=out.max(1)[1]
        loss+=F.nll_loss(out,data.y.view(-1),reduction='sum').item()
        correct+=pred.eq(data.y.view(-1)).sum().item()
    return loss/len(loader.dataset), correct/len(loader.dataset)