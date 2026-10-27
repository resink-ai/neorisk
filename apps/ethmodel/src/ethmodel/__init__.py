"""Ethereum bad-address model v0: the modeling plan's skeleton, not a tuned model.

data      load a sample from eth-collect, split the labels, apply the timing rule
tokens    each address's transfers -> a sequence of field tokens
model     the encoder, masked event modeling and same-address contrast
features  the hand-built baseline (~20 aggregates per address)
head      the positive-unlabeled head, the one-hop graph score, recall@k
expand    evaluation on held-out labels and the candidate list with evidence
adapter   the model as a `bench discover` Method, with held-out labels as the reviewer
"""
