PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE years (
          year INTEGER PRIMARY KEY,
          label TEXT NOT NULL
        );
INSERT INTO years VALUES(2026,'2026 Academy Awards Nominees');
CREATE TABLE categories (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          name TEXT NOT NULL,
          year_started INTEGER,
          year_ended INTEGER,
          UNIQUE(year, name)
        );
INSERT INTO categories VALUES(145,2026,'Actor in a Leading Role',1929,NULL);
INSERT INTO categories VALUES(146,2026,'Actor in a Supporting Role',1937,NULL);
INSERT INTO categories VALUES(147,2026,'Actress in a Leading Role',1929,NULL);
INSERT INTO categories VALUES(148,2026,'Actress in a Supporting Role',1936,NULL);
INSERT INTO categories VALUES(149,2026,'Animated Feature Film',2002,NULL);
INSERT INTO categories VALUES(150,2026,'Animated Short Film',1932,NULL);
INSERT INTO categories VALUES(151,2026,'Best Picture',1929,NULL);
INSERT INTO categories VALUES(152,2026,'Casting',2026,NULL);
INSERT INTO categories VALUES(153,2026,'Cinematography',1929,NULL);
INSERT INTO categories VALUES(154,2026,'Costume Design',1949,NULL);
INSERT INTO categories VALUES(155,2026,'Directing',1929,NULL);
INSERT INTO categories VALUES(156,2026,'Documentary Feature Film',1942,NULL);
INSERT INTO categories VALUES(157,2026,'Documentary Short Film',1942,NULL);
INSERT INTO categories VALUES(158,2026,'Film Editing',1934,NULL);
INSERT INTO categories VALUES(159,2026,'International Feature Film',1957,NULL);
INSERT INTO categories VALUES(160,2026,'Live Action Short Film',1974,NULL);
INSERT INTO categories VALUES(161,2026,'Makeup and Hairstyling',1981,NULL);
INSERT INTO categories VALUES(162,2026,'Music (Original Score)',1935,NULL);
INSERT INTO categories VALUES(163,2026,'Music (Original Song)',1935,NULL);
INSERT INTO categories VALUES(164,2026,'Production Design',1929,NULL);
INSERT INTO categories VALUES(165,2026,'Sound',2021,NULL);
INSERT INTO categories VALUES(166,2026,'Visual Effects',1977,NULL);
INSERT INTO categories VALUES(167,2026,'Writing (Adapted Screenplay)',1929,NULL);
INSERT INTO categories VALUES(168,2026,'Writing (Original Screenplay)',1940,NULL);
CREATE TABLE films (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL
        , external_id TEXT);
INSERT INTO films VALUES('FilmID004','Marty Supreme','FilmID004');
INSERT INTO films VALUES('FilmID002','One Battle After Another','FilmID002');
INSERT INTO films VALUES('FilmID012','Blue Moon','FilmID012');
INSERT INTO films VALUES('FilmID001','Sinners','FilmID001');
INSERT INTO films VALUES('FilmID009','The Secret Agent','FilmID009');
INSERT INTO films VALUES('FilmID003','Frankenstein','FilmID003');
INSERT INTO films VALUES('FilmID005','Sentimental Value','FilmID005');
INSERT INTO films VALUES('FilmID006','Hamnet','FilmID006');
INSERT INTO films VALUES('FilmID015','If I Had Legs I''d Kick You','FilmID015');
INSERT INTO films VALUES('FilmID016','Song Sung Blue','FilmID016');
INSERT INTO films VALUES('FilmID007','Bugonia','FilmID007');
INSERT INTO films VALUES('FilmID017','Weapons','FilmID017');
INSERT INTO films VALUES('FilmID022','Arco','FilmID022');
INSERT INTO films VALUES('FilmID023','Elio','FilmID023');
INSERT INTO films VALUES('FilmID013','KPop Demon Hunters','FilmID013');
INSERT INTO films VALUES('FilmID024','Little Amélie','FilmID024');
INSERT INTO films VALUES('FilmID025','Zootopia 2','FilmID025');
INSERT INTO films VALUES('FilmID046','Butterfly','FilmID046');
INSERT INTO films VALUES('FilmID047','Forevergreen','FilmID047');
INSERT INTO films VALUES('FilmID048','The Girl Who Cried Pearls','FilmID048');
INSERT INTO films VALUES('FilmID049','Retirement Plan','FilmID049');
INSERT INTO films VALUES('FilmID050','The Three Sisters','FilmID050');
INSERT INTO films VALUES('FilmID008','F1','FilmID008');
INSERT INTO films VALUES('FilmID010','Train Dreams','FilmID010');
INSERT INTO films VALUES('FilmID011','Avatar: Fire and Ash','FilmID011');
INSERT INTO films VALUES('FilmID029','The Alabama Solution','FilmID029');
INSERT INTO films VALUES('FilmID027','Come See Me in the Good Light','FilmID027');
INSERT INTO films VALUES('FilmID026','Cutting Through the Rocks','FilmID026');
INSERT INTO films VALUES('FilmID028','Mr. Nobody Against Putin','FilmID028');
INSERT INTO films VALUES('FilmID030','The Perfect Neighbor','FilmID030');
INSERT INTO films VALUES('FilmID041','All the Empty Rooms','FilmID041');
INSERT INTO films VALUES('FilmID042','Armed Only With A Camera: The Life and Death of Brent Renaud','FilmID042');
INSERT INTO films VALUES('FilmID043','Children No More: Were And Are Gone','FilmID043');
INSERT INTO films VALUES('FilmID044','The Devil is Busy','FilmID044');
INSERT INTO films VALUES('FilmID045','Perfectly a Strangeness','FilmID045');
INSERT INTO films VALUES('FilmID018','It Was Just An Accident','FilmID018');
INSERT INTO films VALUES('FilmID014','Sirāt','FilmID014');
INSERT INTO films VALUES('FilmID021','The Voice of Hind Rajab','FilmID021');
INSERT INTO films VALUES('FilmID036','Butcher''s Stain','FilmID036');
INSERT INTO films VALUES('FilmID037','A Friend of Dorothy','FilmID037');
INSERT INTO films VALUES('FilmID038','Jane Austen''s Period Drama','FilmID038');
INSERT INTO films VALUES('FilmID039','The Singers','FilmID039');
INSERT INTO films VALUES('FilmID040','Two People Exchanging Saliva','FilmID040');
INSERT INTO films VALUES('FilmID031','Kokuho','FilmID031');
INSERT INTO films VALUES('FilmID032','The Smashing Machine','FilmID032');
INSERT INTO films VALUES('FilmID033','The Ugly Stepsister','FilmID033');
INSERT INTO films VALUES('FilmID019','Diane Warren: Relentless','FilmID019');
INSERT INTO films VALUES('FilmID020','Viva Verdi!','FilmID020');
INSERT INTO films VALUES('FilmID034','Jurassic World Rebirth','FilmID034');
INSERT INTO films VALUES('FilmID035','The Lost Bus','FilmID035');
CREATE TABLE film_years (
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          base_free TEXT DEFAULT '',
          base_subscription TEXT DEFAULT '',
          base_rent TEXT DEFAULT '',
          base_theaters TEXT DEFAULT '',
          PRIMARY KEY(year, film_id)
        );
INSERT INTO film_years VALUES(2026,'FilmID004','','','Apple, Amazon, Google Play','');
INSERT INTO film_years VALUES(2026,'FilmID002','','HBO MAX','Apple, Hulu, Amazon, etc','');
INSERT INTO film_years VALUES(2026,'FilmID012','','','Apple, Amazon, Google Play, etc','');
INSERT INTO film_years VALUES(2026,'FilmID001','','HBO MAX','Apple, Hulu, Amazon, etc','');
INSERT INTO film_years VALUES(2026,'FilmID009','','','Apple, Google Play, etc','');
INSERT INTO film_years VALUES(2026,'FilmID003','','Netflix','','');
INSERT INTO film_years VALUES(2026,'FilmID005','','','Apple, Amazon, Google Play','');
INSERT INTO film_years VALUES(2026,'FilmID006','','','Apple, Amazon, Google Play','');
INSERT INTO film_years VALUES(2026,'FilmID015','','HBO MAX','Apple, Hulu, Amazon, etc','');
INSERT INTO film_years VALUES(2026,'FilmID016','','','Apple, Amazon, Google Play, etc','');
INSERT INTO film_years VALUES(2026,'FilmID007','','Peacock','Apple, Amazon, Google Play, etc','');
INSERT INTO film_years VALUES(2026,'FilmID017','','HBO MAX','Apple, Hulu, Amazon, etc','');
INSERT INTO film_years VALUES(2026,'FilmID022','','','','Showtimes');
INSERT INTO film_years VALUES(2026,'FilmID023','','Disney+','Apple, Amazon, Google Play, etc','');
INSERT INTO film_years VALUES(2026,'FilmID013','','Netflix','','');
INSERT INTO film_years VALUES(2026,'FilmID024','','','Apple, Amazon, Google Play, etc','');
INSERT INTO film_years VALUES(2026,'FilmID025','','','Apple, Amazon, Google Play, etc','');
INSERT INTO film_years VALUES(2026,'FilmID046','Youtube','','','');
INSERT INTO film_years VALUES(2026,'FilmID047','Youtube','','','');
INSERT INTO film_years VALUES(2026,'FilmID048','NFBC - requires VPN','','','');
INSERT INTO film_years VALUES(2026,'FilmID049','Youtube','','','');
INSERT INTO film_years VALUES(2026,'FilmID050','','','Not available','');
INSERT INTO film_years VALUES(2026,'FilmID008','','Apple','Amazon, Google Play, etc','');
INSERT INTO film_years VALUES(2026,'FilmID010','','Netflix','','');
INSERT INTO film_years VALUES(2026,'FilmID011','','','','Showtimes');
INSERT INTO film_years VALUES(2026,'FilmID029','','HBO MAX','Hulu, Amazon, etc','');
INSERT INTO film_years VALUES(2026,'FilmID027','','Apple','','');
INSERT INTO film_years VALUES(2026,'FilmID026','','','DocPlay beginning March 2','');
INSERT INTO film_years VALUES(2026,'FilmID028','','Roku','Apple, Fandango','');
INSERT INTO film_years VALUES(2026,'FilmID030','','Netflix','','');
INSERT INTO film_years VALUES(2026,'FilmID041','','Netflix','','');
INSERT INTO film_years VALUES(2026,'FilmID042','','HBO MAX','Hulu, Amazon, etc','');
INSERT INTO film_years VALUES(2026,'FilmID043','','','Not available','');
INSERT INTO film_years VALUES(2026,'FilmID044','','HBO MAX','Hulu, Amazon, etc','');
INSERT INTO film_years VALUES(2026,'FilmID045','','','Patreon','');
INSERT INTO film_years VALUES(2026,'FilmID018','','','Apple, Amazon, Google Play, etc','');
INSERT INTO film_years VALUES(2026,'FilmID014','','','','Showtimes');
INSERT INTO film_years VALUES(2026,'FilmID021','','','','Showtimes');
INSERT INTO film_years VALUES(2026,'FilmID036','','','Not available','');
INSERT INTO film_years VALUES(2026,'FilmID037','','Disney+','','');
INSERT INTO film_years VALUES(2026,'FilmID038','YouTube','','','');
INSERT INTO film_years VALUES(2026,'FilmID039','','Netflix','','');
INSERT INTO film_years VALUES(2026,'FilmID040','Youtube','','','');
INSERT INTO film_years VALUES(2026,'FilmID031','','','','Showtimes');
INSERT INTO film_years VALUES(2026,'FilmID032','','HBO MAX','Apple, Hulu, Amazon, etc','');
INSERT INTO film_years VALUES(2026,'FilmID033','','Disney+, Hulu','Apple, Amazon, Google Play, etc','');
INSERT INTO film_years VALUES(2026,'FilmID019','','','Apple, Amazon, Google Play, etc','');
INSERT INTO film_years VALUES(2026,'FilmID020','','','Jolt.film','');
INSERT INTO film_years VALUES(2026,'FilmID034','','Peacock','Apple, Amazon, Google Play, etc','');
INSERT INTO film_years VALUES(2026,'FilmID035','','Apple','Amazon Prime','');
CREATE TABLE nominations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          nominee TEXT DEFAULT ''
        );
INSERT INTO nominations VALUES(751,2026,145,'FilmID004','Timothée Chalamet');
INSERT INTO nominations VALUES(752,2026,145,'FilmID002','Leonardo DiCaprio');
INSERT INTO nominations VALUES(753,2026,145,'FilmID012','Ethan Hawke');
INSERT INTO nominations VALUES(754,2026,145,'FilmID001','Michael B. Jordan');
INSERT INTO nominations VALUES(755,2026,145,'FilmID009','Wagner Moura');
INSERT INTO nominations VALUES(756,2026,146,'FilmID002','Benicio Del Toro');
INSERT INTO nominations VALUES(757,2026,146,'FilmID003','Jacob Elordi');
INSERT INTO nominations VALUES(758,2026,146,'FilmID001','Delroy Lindo');
INSERT INTO nominations VALUES(759,2026,146,'FilmID002','Sean Penn');
INSERT INTO nominations VALUES(760,2026,146,'FilmID005','Stellan Skarsgård');
INSERT INTO nominations VALUES(761,2026,147,'FilmID006','Jessie Buckley');
INSERT INTO nominations VALUES(762,2026,147,'FilmID015','Rose Byrne');
INSERT INTO nominations VALUES(763,2026,147,'FilmID016','Kate Hudson');
INSERT INTO nominations VALUES(764,2026,147,'FilmID005','Renate Reinsve');
INSERT INTO nominations VALUES(765,2026,147,'FilmID007','Emma Stone');
INSERT INTO nominations VALUES(766,2026,148,'FilmID005','Elle Fanning');
INSERT INTO nominations VALUES(767,2026,148,'FilmID005','Inga Ibsdotter Lilleaas');
INSERT INTO nominations VALUES(768,2026,148,'FilmID017','Amy Madigan');
INSERT INTO nominations VALUES(769,2026,148,'FilmID001','Wunmi Mosaku');
INSERT INTO nominations VALUES(770,2026,148,'FilmID002','Teyana Taylor');
INSERT INTO nominations VALUES(771,2026,149,'FilmID022','');
INSERT INTO nominations VALUES(772,2026,149,'FilmID023','');
INSERT INTO nominations VALUES(773,2026,149,'FilmID013','');
INSERT INTO nominations VALUES(774,2026,149,'FilmID024','');
INSERT INTO nominations VALUES(775,2026,149,'FilmID025','');
INSERT INTO nominations VALUES(776,2026,150,'FilmID046','');
INSERT INTO nominations VALUES(777,2026,150,'FilmID047','');
INSERT INTO nominations VALUES(778,2026,150,'FilmID048','');
INSERT INTO nominations VALUES(779,2026,150,'FilmID049','');
INSERT INTO nominations VALUES(780,2026,150,'FilmID050','');
INSERT INTO nominations VALUES(781,2026,151,'FilmID007','');
INSERT INTO nominations VALUES(782,2026,151,'FilmID008','');
INSERT INTO nominations VALUES(783,2026,151,'FilmID003','');
INSERT INTO nominations VALUES(784,2026,151,'FilmID006','');
INSERT INTO nominations VALUES(785,2026,151,'FilmID004','');
INSERT INTO nominations VALUES(786,2026,151,'FilmID002','');
INSERT INTO nominations VALUES(787,2026,151,'FilmID009','');
INSERT INTO nominations VALUES(788,2026,151,'FilmID005','');
INSERT INTO nominations VALUES(789,2026,151,'FilmID001','');
INSERT INTO nominations VALUES(790,2026,151,'FilmID010','');
INSERT INTO nominations VALUES(791,2026,152,'FilmID006','Nina Gold');
INSERT INTO nominations VALUES(792,2026,152,'FilmID004','Jennifer Venditti');
INSERT INTO nominations VALUES(793,2026,152,'FilmID002','Cassandra Kulukundis');
INSERT INTO nominations VALUES(794,2026,152,'FilmID009','Gabriel Domingues');
INSERT INTO nominations VALUES(795,2026,152,'FilmID001','Francine Maisler');
INSERT INTO nominations VALUES(796,2026,153,'FilmID003','Dan Laustsen');
INSERT INTO nominations VALUES(797,2026,153,'FilmID004','Darius Khondji');
INSERT INTO nominations VALUES(798,2026,153,'FilmID002','Michael Bauman');
INSERT INTO nominations VALUES(799,2026,153,'FilmID001','Autumn Durald Arkapaw');
INSERT INTO nominations VALUES(800,2026,153,'FilmID010','Adolpho Veloso');
INSERT INTO nominations VALUES(801,2026,154,'FilmID011','Deborah L. Scott');
INSERT INTO nominations VALUES(802,2026,154,'FilmID003','Kate Hawley');
INSERT INTO nominations VALUES(803,2026,154,'FilmID006','Malgosia Turzanska');
INSERT INTO nominations VALUES(804,2026,154,'FilmID004','Miyako Bellizzi');
INSERT INTO nominations VALUES(805,2026,154,'FilmID001','Ruth E. Carter');
INSERT INTO nominations VALUES(806,2026,155,'FilmID006','Chloé Zhao');
INSERT INTO nominations VALUES(807,2026,155,'FilmID004','Josh Safdie');
INSERT INTO nominations VALUES(808,2026,155,'FilmID002','Paul Thomas Anderson');
INSERT INTO nominations VALUES(809,2026,155,'FilmID005','Joachim Trier');
INSERT INTO nominations VALUES(810,2026,155,'FilmID001','Ryan Coogler');
INSERT INTO nominations VALUES(811,2026,156,'FilmID029','');
INSERT INTO nominations VALUES(812,2026,156,'FilmID027','');
INSERT INTO nominations VALUES(813,2026,156,'FilmID026','');
INSERT INTO nominations VALUES(814,2026,156,'FilmID028','');
INSERT INTO nominations VALUES(815,2026,156,'FilmID030','');
INSERT INTO nominations VALUES(816,2026,157,'FilmID041','');
INSERT INTO nominations VALUES(817,2026,157,'FilmID042','');
INSERT INTO nominations VALUES(818,2026,157,'FilmID043','');
INSERT INTO nominations VALUES(819,2026,157,'FilmID044','');
INSERT INTO nominations VALUES(820,2026,157,'FilmID045','');
INSERT INTO nominations VALUES(821,2026,158,'FilmID008','Stephen Mirrione');
INSERT INTO nominations VALUES(822,2026,158,'FilmID004','Ronald Bronstein and Josh Safdie');
INSERT INTO nominations VALUES(823,2026,158,'FilmID002','Andy Jurgensen');
INSERT INTO nominations VALUES(824,2026,158,'FilmID005','Olivier Bugge Coutté');
INSERT INTO nominations VALUES(825,2026,158,'FilmID001','Michael P. Shawver');
INSERT INTO nominations VALUES(826,2026,159,'FilmID009','Brazil');
INSERT INTO nominations VALUES(827,2026,159,'FilmID018','France');
INSERT INTO nominations VALUES(828,2026,159,'FilmID005','Norway');
INSERT INTO nominations VALUES(829,2026,159,'FilmID014','Spain');
INSERT INTO nominations VALUES(830,2026,159,'FilmID021','Tunisia');
INSERT INTO nominations VALUES(831,2026,160,'FilmID036','');
INSERT INTO nominations VALUES(832,2026,160,'FilmID037','');
INSERT INTO nominations VALUES(833,2026,160,'FilmID038','');
INSERT INTO nominations VALUES(834,2026,160,'FilmID039','');
INSERT INTO nominations VALUES(835,2026,160,'FilmID040','');
INSERT INTO nominations VALUES(836,2026,161,'FilmID003','Mike Hill, Jordan Samuel and Cliona Furey');
INSERT INTO nominations VALUES(837,2026,161,'FilmID031','Kyoko Toyokawa, Naomi Hibino and Tadashi Nishimatsu');
INSERT INTO nominations VALUES(838,2026,161,'FilmID001','Ken Diaz, Mike Fontaine and Shunika Terry');
INSERT INTO nominations VALUES(839,2026,161,'FilmID032','Kazu Hiro, Glen Griffin and Bjoern Rehbein');
INSERT INTO nominations VALUES(840,2026,161,'FilmID033','Thomas Foldberg and Anne Cathrine Sauerberg');
INSERT INTO nominations VALUES(841,2026,162,'FilmID007','Jerskin Fendrix');
INSERT INTO nominations VALUES(842,2026,162,'FilmID003','Alexandre Desplat');
INSERT INTO nominations VALUES(843,2026,162,'FilmID006','Max Richter');
INSERT INTO nominations VALUES(844,2026,162,'FilmID002','Jonny Greenwood');
INSERT INTO nominations VALUES(845,2026,162,'FilmID001','Ludwig Goransson');
INSERT INTO nominations VALUES(846,2026,163,'FilmID019','Diane Warren');
INSERT INTO nominations VALUES(847,2026,163,'FilmID013','EJAE, Mark Sonnenblick, Joong Gyu Kwak, Yu Han Lee, Hee Dong Nam, Jeong Hoon Seo and Teddy Park');
INSERT INTO nominations VALUES(848,2026,163,'FilmID001','Raphael Saadiq and Ludwig Goransson');
INSERT INTO nominations VALUES(849,2026,163,'FilmID020','Nicholas Pike');
INSERT INTO nominations VALUES(850,2026,163,'FilmID010','Nick Cave and Bryce Dessner;');
INSERT INTO nominations VALUES(851,2026,164,'FilmID003','Production Design: Tamara Deverell; Set Decoration: Shane Vieau');
INSERT INTO nominations VALUES(852,2026,164,'FilmID006','Production Design: Fiona Crombie; Set Decoration: Alice Felton');
INSERT INTO nominations VALUES(853,2026,164,'FilmID004','Production Design: Jack Fisk; Set Decoration: Adam Willis');
INSERT INTO nominations VALUES(854,2026,164,'FilmID002','Production Design: Florencia Martin; Set Decoration: Anthony Carlino');
INSERT INTO nominations VALUES(855,2026,164,'FilmID001','Production Design: Hannah Beachler; Set Decoration: Monique Champagne');
INSERT INTO nominations VALUES(856,2026,165,'FilmID008','Gareth John, Al Nelson, Gwendolyn Yates Whittle, Gary A. Rizzo and Juan Peralta');
INSERT INTO nominations VALUES(857,2026,165,'FilmID003','Greg Chapman, Nathan Robitaille, Nelson Ferreira, Christian Cooke and Brad Zoern');
INSERT INTO nominations VALUES(858,2026,165,'FilmID002','José Antonio García, Christopher Scarabosio and Tony Villaflor');
INSERT INTO nominations VALUES(859,2026,165,'FilmID001','Chris Welcker, Benjamin A. Burtt, Felipe Pacheco, Brandon Proctor and Steve Boeddeker');
INSERT INTO nominations VALUES(860,2026,165,'FilmID014','Amanda Villavieja, Laia Casanovas and Yasmina Praderas');
INSERT INTO nominations VALUES(861,2026,166,'FilmID011','Joe Letteri, Richard Baneham, Eric Saindon and Daniel Barrett');
INSERT INTO nominations VALUES(862,2026,166,'FilmID008','Ryan Tudhope, Nicolas Chevallier, Robert Harrington and Keith Dawson');
INSERT INTO nominations VALUES(863,2026,166,'FilmID034','David Vickery, Stephen Aplin, Charmaine Chan and Neil Corbould');
INSERT INTO nominations VALUES(864,2026,166,'FilmID035','Charlie Noble, David Zaretti, Russell Bowen and Brandon K. McLaughlin');
INSERT INTO nominations VALUES(865,2026,166,'FilmID001','Michael Ralla, Espen Nordahl, Guido Wolter and Donnie Dean');
INSERT INTO nominations VALUES(866,2026,167,'FilmID007','Will Tracy');
INSERT INTO nominations VALUES(867,2026,167,'FilmID003','Guillermo del Toro');
INSERT INTO nominations VALUES(868,2026,167,'FilmID006','Chloé Zhao & Maggie O''Farrell');
INSERT INTO nominations VALUES(869,2026,167,'FilmID002','Paul Thomas Anderson');
INSERT INTO nominations VALUES(870,2026,167,'FilmID010','Clint Bentley & Greg Kwedar');
INSERT INTO nominations VALUES(871,2026,168,'FilmID012','Robert Kaplow');
INSERT INTO nominations VALUES(872,2026,168,'FilmID018','Jafar Panahi; Script collaborators - Nader Saïvar, Shadmehr Rastin, Mehdi Mahmoudian');
INSERT INTO nominations VALUES(873,2026,168,'FilmID004','Ronald Bronstein & Josh Safdie');
INSERT INTO nominations VALUES(874,2026,168,'FilmID005','Eskil Vogt, Joachim Trier');
INSERT INTO nominations VALUES(875,2026,168,'FilmID001','Ryan Coogler');
CREATE TABLE default_seen (
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          PRIMARY KEY(year, film_id)
        );
CREATE TABLE user_seen (
          user_key TEXT NOT NULL,
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          seen INTEGER NOT NULL CHECK (seen IN (0,1)),
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(user_key, year, film_id)
        );
CREATE TABLE admin_watch_links (
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          url TEXT NOT NULL,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(year, film_id)
        );
CREATE TABLE scraped_posters (
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          url TEXT NOT NULL,
          source TEXT DEFAULT 'google_images',
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(year, film_id)
        );
CREATE TABLE admin_posters (
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          url TEXT NOT NULL,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(year, film_id)
        );
CREATE TABLE user_picks (
          user_key TEXT NOT NULL,
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(user_key, year, category_id)
        );
CREATE TABLE category_winners (
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(year, category_id)
        );
CREATE TABLE admin_watch_labels (
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          free_to_watch INTEGER NOT NULL CHECK (free_to_watch IN (0,1)) DEFAULT 0,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(year, film_id)
        );
CREATE TABLE admin_banners (
          year INTEGER PRIMARY KEY REFERENCES years(year) ON DELETE CASCADE,
          enabled INTEGER NOT NULL CHECK (enabled IN (0,1)) DEFAULT 1,
          text TEXT NOT NULL DEFAULT ''
        );
CREATE TABLE admin_event_modes (
          year INTEGER PRIMARY KEY REFERENCES years(year) ON DELETE CASCADE,
          enabled INTEGER NOT NULL CHECK (enabled IN (0,1)) DEFAULT 0
        );
CREATE TABLE admin_voting_locks (
          year INTEGER PRIMARY KEY REFERENCES years(year) ON DELETE CASCADE,
          enabled INTEGER NOT NULL CHECK (enabled IN (0,1)) DEFAULT 0
        );
CREATE TABLE contact_submissions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          email TEXT NOT NULL,
          topic TEXT DEFAULT '',
          message TEXT NOT NULL,
          sent INTEGER NOT NULL CHECK (sent IN (0,1)) DEFAULT 0,
          send_error TEXT DEFAULT '',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
CREATE TABLE year_import_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          year INTEGER NOT NULL,
          source_path TEXT NOT NULL,
          data_hash TEXT NOT NULL,
          schema_version INTEGER,
          status TEXT NOT NULL,
          details TEXT DEFAULT '',
          imported_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
INSERT INTO year_import_runs VALUES(1,2026,'data/nominees.json','997e429b45707174b229d994863f1ba7dee3c6725acc5adb12b4f9663390caa5',1,'success','Imported successfully','2026-02-18 16:57:35');
INSERT INTO sqlite_sequence VALUES('categories',168);
INSERT INTO sqlite_sequence VALUES('nominations',875);
INSERT INTO sqlite_sequence VALUES('year_import_runs',1);
CREATE UNIQUE INDEX idx_films_external_id
        ON films(external_id) WHERE external_id IS NOT NULL AND external_id <> ''
        ;
COMMIT;
