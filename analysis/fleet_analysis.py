import pandas as pd, numpy as np, math
B='C:/Users/tdgca/Downloads/urbAIn_kit/urbAIn_kit/data/'
A=['Centro + Parte Vieja','Gros + Zurriola + Ategorrieta','Amara + Egia + Loiola + Riberas','Antiguo + Ondarreta + Ibaeta','Altza + Intxaurrondo + Bidebieta + Herrera','Aiete']
S=['passenger_transport','food_delivery']
d=pd.read_csv(B+'mercado/historico_demanda.csv.gz')
d['ts']=pd.to_datetime(d.timestamp_local.str[:19]); d['date']=d.ts.dt.date; d['hour']=d.ts.dt.hour
nd=d.date.nunique(); print('days',nd,d.date.min(),d.date.max(),'weeks',nd/7, 'rows',len(d))
x=d[d.service_id.isin(S)&d.origin_market.isin(A)]
g=(x.groupby(['origin_market','hour','service_id']).size()/nd*1.4).rename('avg_requests_per_day_f1').reset_index()
g.to_csv('C:/Users/tdgca/Downloads/urbAIn_kit/urbAIn_kit/analysis/demand_by_area_hour.csv',index=False,float_format='%.2f')
z=pd.read_csv(B+'mercado/zonas.csv'); zm=dict(zip(z.zone_id,z.market_area))
e=pd.read_csv(B+'mercado/experiencias_clientes.csv'); e['area']=e.origin_zone.map(zm)
e=e[e.service_id.isin(S)]
print(e.groupby('service_id')[['observed_fare_eur','observed_distance_km','observed_trip_minutes','observed_pickup_minutes']].mean())
# fare fit
for s in S:
    q=e[e.service_id==s].dropna(subset=['observed_fare_eur','observed_distance_km'])
    p=np.polyfit(q.observed_distance_km,q.observed_fare_eur,1); print(s,'fare fit base %.2f perkm %.2f'%(p[1],p[0]))
    print(q.groupby('winner_kind').observed_fare_eur.mean())
ea=e.groupby('area')[['observed_distance_km','observed_trip_minutes']].mean()
print(ea)
tot=g.groupby('origin_market').avg_requests_per_day_f1.sum(); print(tot, tot.sum())
hr=g.groupby(['origin_market','hour']).avg_requests_per_day_f1.sum().unstack(0)
pk=hr.max(); pkh=hr.idxmax(); print(pd.DataFrame({'peak':pk,'h':pkh}))
FARE={'passenger_transport':(2.95,0.98),'food_delivery':(2.90,0.95)}
mix=g.groupby(['origin_market','service_id']).avg_requests_per_day_f1.sum().unstack().fillna(0)
USABLE=96 # km per 20->100 charge, bike high_low (120km*0.8)
rows=[]
for sc,sh in [('lean',.05),('base',.08),('aggr',.12)]:
    V=C=srv=mar=0
    for a in A:
        km=ea.loc[a,'observed_distance_km']; tm=ea.loc[a,'observed_trip_minutes']
        empty_km=1.0
        cyc=6+tm+5+(km+empty_km)/USABLE*66.7
        v=math.ceil(pk[a]*sh*cyc/60); c=max(1,math.ceil(v/20))
        dd=tot[a]*sh
        m=0
        for s in S:
            f0,f1=FARE[s]; n=mix.loc[a].get(s,0)*sh
            m+=n*(f0+f1*km-2.20-0.30*km-km*0.0083*1.2*0.25)
        # charger hours check
        chh=dd*(km+empty_km)/USABLE*66.7/60
        rows.append((sc,a[:7],round(pk[a]*sh,1),round(cyc,1),v,c,round(dd,1),round(m,1),round(chh,1)))
        V+=v;C+=c;srv+=dd;mar+=m
    dep=C*6000/18/4+V*1500/15/4
    prof=mar*28-dep
    print(sc,'veh',V,'chg',C,'served/day %.0f score %.1f margin/mo %.0f dep/mo %.0f profit/mo %.0f'%(srv,100*srv/(srv+186),mar*28,dep,prof))
print(pd.DataFrame(rows,columns=['sc','area','peak_req_h','cycle_min','veh','chg','req_day','margin_day','charger_h_day']).to_string())
# anchor share within 1km
def hav(la1,lo1,la2,lo2):
    la1,lo1,la2,lo2=map(np.radians,[la1,lo1,la2,lo2]); return 6371*2*np.arcsin(np.sqrt(np.sin((la2-la1)/2)**2+np.cos(la1)*np.cos(la2)*np.sin((lo2-lo1)/2)**2))
zz=z.set_index('zone_id')
for a in A:
    q=x[x.origin_market==a]; top=q.origin_h3.value_counts().index[0]
    la,lo=zz.loc[top,'centroid_lat'],zz.loc[top,'centroid_lon']
    dist=hav(la,lo,q.origin_lat.values,q.origin_lon.values)
    print(a[:7],top,'top cell share %.1f%%'%(100*(q.origin_h3==top).mean()),'<=1km %.0f%%'%(100*(dist<=1).mean()),'<=1.5km %.0f%%'%(100*(dist<=1.5).mean()))
