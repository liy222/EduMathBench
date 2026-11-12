"""Recording helper for explicitly authored content, not a content generator."""
from variant_authoring import Session

class Drafts(Session):
    def __init__(self,batch):super().__init__(batch,revision='v2')
    def q(self,i,stem,options,answer,change,proof,expr=None,values=None,spec=None):
        difficulty=self.parents[i-1]['difficulty']
        super().add(i,stem,options,answer,change,proof,difficulty,expr,values,spec)
        self.rows[-1]['difficulty_reason']='母题来源暂定标签为'+difficulty+'；本轮逐题改编保留主要知识，题面推理依据：'+proof
        self.rows[-1]['difficulty_basis']='parent_source_label_plus_author_task_review_not_empirical'
