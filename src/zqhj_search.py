"""Area-covering search from public bounds and broadcast-discovered team members."""
import math


class StripSearch:
    def __init__(self,uid,spacing=220.,margin=250.):
        self.uid=uid;self.spacing=spacing;self.margin=margin
        self.roster=None;self.signature=None;self.points=[];self.index=0
        self.laps=0

    def goal(self,position,bounds,peers):
        if not bounds:return position[0],position[1]+500.
        # Freeze a complete three-aircraft roster learned only through radio.
        # Temporary packet loss must not repeatedly reshuffle flight assignments.
        discovered=tuple(sorted({self.uid,*peers}))
        if self.roster is None and len(discovered)==3:self.roster=discovered
        roster=self.roster or (self.uid,)
        signature=(tuple(bounds),roster)
        if signature!=self.signature:
            self.signature=signature
            xmin,xmax,ymin,ymax=bounds
            mx,my=min(self.margin,(xmax-xmin)/4),min(self.margin,(ymax-ymin)/4)
            lo,hi=xmin+mx,xmax-mx
            count=max(1,math.ceil((hi-lo)/self.spacing)+1)
            lanes=[lo+(hi-lo)*i/max(1,count-1) for i in range(count)]
            rank=roster.index(self.uid)
            assigned=lanes[rank::len(roster)] or [(lo+hi)/2]
            # Start near the aircraft; each strip is visited in both directions
            # through a continuous boustrophedon list, without hidden road input.
            if abs(position[0]-assigned[-1])<abs(position[0]-assigned[0]):assigned.reverse()
            forward=abs(position[1]-(ymin+my)) <= abs(position[1]-(ymax-my))
            self.points=[]
            for x in assigned:
                ys=(ymin+my,ymax-my) if forward else (ymax-my,ymin+my)
                self.points.extend((x,y) for y in ys);forward=not forward
            self.index=0
        if math.dist(position,self.points[self.index])<110.:
            self.index+=1
            if self.index>=len(self.points):
                self.points.reverse();self.index=0;self.laps+=1
        return self.points[self.index]
