/**
 * 四六级阅读理解文章库（学生端外语学习 · 阅读理解页面）
 *
 * 内容说明：
 * - tag 区分考试级别：'CET-4'（大学英语四级）/ 'CET-6'（大学英语六级）
 * - 篇幅贴合真题：四级 250~330 词，六级 340~430 词
 * - 难度映射：CET-4 → B1/B2，CET-6 → B2/C1
 * - 选题来源：约半数取材 2025-2026 全球热点新闻（联网调研素材），
 *   约半数基于历年四六级经典话题（科技与生活/环保/教育/健康等）重新组织语言
 * - theme 字段标注题材与素材年份，便于教学检索
 */

export const CET4_ARTICLES = [
    {
        id: 'cet4-01',
        title: 'The Science of Napping',
        tag: 'CET-4',
        level: 'B1',
        theme: '健康·睡眠（经典话题）',
        text: `Few habits divide people as clearly as the afternoon nap. Some workers guard their midday rest as fiercely as their morning coffee, while others insist that sleeping at work is a sign of laziness. Science, however, is increasingly on the side of the nappers.

Studies show that a short sleep of ten to twenty minutes can improve memory, alertness and mood without leaving the sleeper feeling tired afterwards. The key is timing. Once a nap lasts longer than about thirty minutes, the brain enters a deeper stage of sleep, and waking up from that stage produces the heavy, confused feeling known as sleep inertia. For this reason, sleep experts suggest setting an alarm and keeping naps short and regular.

The Japanese workplace offers an interesting example. "Inemuri", which means "sleeping while present", has long been accepted as a sign of hard work rather than weakness. A busy employee who dozes at his desk is seen as someone who pushed himself too far, not someone who is avoiding his duties. In recent years, some companies have gone further and built nap rooms with dark curtains and comfortable chairs, hoping that rested workers will make fewer mistakes and better decisions.

Not everyone agrees, of course. Critics warn that the habit can cover up deeper problems, such as poor night-time sleep or long working hours. A nap, they argue, should be a helper, not a cure. If you need one every single day, the real question is what is happening during the night.

The safest conclusion is simple: a short nap can be a useful tool, but it works best when night sleep is already good. Like a small snack between meals, it supports a healthy pattern; it cannot replace the main dish.`
    },
    {
        id: 'cet4-02',
        title: 'Your Data, Their Business',
        tag: 'CET-4',
        level: 'B2',
        theme: '科技·青少年隐私（2025 热点：TikTok 隐私和解）',
        text: `When you open a free app, you are often the product. This uncomfortable truth gained fresh attention in 2025, when a popular short-video platform agreed to pay hundreds of millions of dollars to settle accusations that it collected large amounts of personal data from children under thirteen without proper permission. Parents around the world reacted with alarm, but experts say the settlement is only the beginning of the conversation.

The core problem is that free services pay their bills with attention and information. Every like, pause and swipe teaches the company something about you, and that knowledge is used to sell advertising. For adults, the trade may be acceptable; for children, many researchers argue it should not be allowed at all, because young users cannot fully understand what they are giving away.

Privacy rules have grown stricter in recent years. In Europe, strong data protection laws require companies to explain clearly what they collect and to obtain real consent. Some countries have gone further and banned certain kinds of targeted advertising to minors. But enforcement is slow, and apps change their design faster than laws change their wording.

What can ordinary users do? Privacy experts offer three practical suggestions. First, check the settings of every app and turn off unnecessary data sharing. Second, think before tapping "agree", and ask what the service needs the information for. Third, teach children early that online spaces are not private places, just as we teach them to be careful on the street.

The market will not fix this problem by itself, because free apps rarely profit from protecting your data. The question is whether users, parents and lawmakers together can push companies toward a fairer deal.`
    },
    {
        id: 'cet4-03',
        title: 'Keeping Cool Without Air Conditioning',
        tag: 'CET-4',
        level: 'B2',
        theme: '气候·低碳建筑（2025 热点：Passivhaus 被动房）',
        text: `On a hot summer day, the simplest solution to a stuffy room is to turn on the air conditioner. But air conditioners are expensive to run and, strangely, they make the city hotter: every unit pushes warm air outside and demands electricity that often comes from burning fuel. As heatwaves become longer and more frequent, a growing number of builders are asking a different question: can a house keep itself cool without any machine at all?

The answer, says a small but devoted community of architects, is yes. The most famous approach is called the Passivhaus, or "passive house", standard. Instead of relying on power, such buildings are designed from the start to stay comfortable. Very thick walls keep the heat out, triple-glazed windows stop warmth from entering, and a clever ventilation system brings in fresh air while recovering the coolness of the inside. In 2025, a house built to this standard in Britain drew wide attention for staying cool without air conditioning during the hottest weeks of the year.

The method has obvious costs. Building to the standard requires careful planning and costs more in the beginning. Homeowners must pay attention to details such as shading and window direction, which are easy to get wrong. And while the standard works well for new houses, improving old buildings is far more difficult and expensive.

Supporters reply that the numbers still favour them. Over a twenty-year period, the money saved on electricity bills often pays back the higher building cost, and the comfort level is far above that of an ordinary room. With summers only getting hotter, they argue, the question is not whether we can afford to build well, but whether we can afford not to.`
    },
    {
        id: 'cet4-04',
        title: 'The Last Bookstore',
        tag: 'CET-4',
        level: 'B1',
        theme: '社会·实体书店（2025 热点：书店关门潮）',
        text: `In many cities, small bookstores are disappearing. Online shops offer lower prices, instant delivery and millions of titles, and e-books can be downloaded in seconds. Why walk to a shop that may not have what you want, when a single click brings it to your door? Yet the closing of each bookstore leaves something behind that no delivery box can replace.

A bookstore is more than a place to buy paper. It is a meeting point where people browse slowly, read the first page of an unknown author, and occasionally talk to strangers about a favourite novel. Many readers say they discover books there that they would never have searched for online. The owner knows the regular customers by name and can recommend exactly the right title for a tired teacher or a curious teenager. No algorithm, however clever, can offer that kind of human warmth.

Some bookstores are fighting back. They add coffee corners, hold evening readings, and host children's storytelling sessions. Others turn themselves into small cultural centres, selling art and gifts alongside books. A few have even found that the experience itself is the product: people come for the atmosphere and leave with a book they never planned to buy.

Experts are careful not to promise a happy ending. The business model is difficult, and many shops still close every year. But the survivors share one lesson: they stopped trying to compete with the internet on price and speed, and instead offered something the internet cannot. In an age of endless choice, there is real value in a place where a friendly person hands you a book and says, "I think you will love this one."`
    },
    {
        id: 'cet4-05',
        title: 'Why Volunteer?',
        tag: 'CET-4',
        level: 'B1',
        theme: '社会·志愿服务（经典话题）',
        text: `Every Saturday morning, university students across China put on simple vests and head to old people's homes, libraries and city parks. They are volunteers, and they give their time without payment. Why do they do it? The reasons, it turns out, are as varied as the volunteers themselves.

For many, volunteering is a way to see the world from another side. A student who helps teach migrant children soon understands how unequal education can be; a young person who visits the elderly learns that loneliness is a quiet illness. These experiences change the way they see their own comfortable lives, and often shape their future career choices.

Others volunteer because it builds skills that classrooms do not teach. Organising a charity sale requires planning and teamwork; leading a reading group develops patience and clear speech. Employers increasingly look for such abilities, and many graduates find that their volunteer record tells a more interesting story than their grades alone.

Of course, there are honest doubts. Some people ask whether volunteering is truly selfless when students do it to improve their resumes. Critics also warn against "volunteer tourism", where people fly across the world for a week, take photos with local children, and leave without making a real difference.

Researchers who study the subject offer a more balanced view. Motivation is almost never pure, they say, and that is fine. What matters is the result: the elderly person who receives a visit, the child who learns to read, the park that becomes cleaner. If a resume gets better along the way, the community still wins. The best volunteering, they conclude, is not about feeling good about yourself; it is about doing something useful and letting the feeling follow.`
    },
    {
        id: 'cet4-06',
        title: 'Running: The World\'s Simplest Sport',
        tag: 'CET-4',
        level: 'B1',
        theme: '健康·运动（经典话题）',
        text: `You do not need a ball, a net or a partner. You need only a pair of shoes and a little courage to start. Running is probably the most accessible sport on earth, and its popularity shows no sign of slowing down.

Doctors have long praised running for its effects on the body. It strengthens the heart, improves blood flow, and helps control weight. Regular runners often report lower blood pressure and better sleep. But the mental benefits may be even more valuable. Many runners describe a calm, clear feeling during and after exercise, and studies suggest that regular aerobic activity can reduce anxiety and lift mild depression. For students facing exams, a daily run can be a simple form of stress relief that does not require any equipment or membership.

The running world has also changed socially. City marathons now attract tens of thousands of participants, many of whom are not racing for prizes but simply to finish. Night runs with colourful lights, trail runs in the mountains, and charity runs in school playgrounds have turned the sport into a social event. WeChat groups share daily distances, and friends encourage each other when one of them feels lazy.

Beginners, however, should respect a few basic rules. Start slowly, increasing distance by no more than ten percent each week, to avoid injuries to the knees and feet. Choose soft surfaces when possible, and wear shoes designed for running rather than fashion. Most importantly, listen to your body: pain is a warning, not a challenge.

The appeal of running is easy to understand. It is cheap, simple and honest. You cannot pretend to have run five kilometres; the road knows the truth. In a world full of complicated solutions, that simple honesty is refreshing.`
    },
    {
        id: 'cet4-07',
        title: 'The Problem With Plastic',
        tag: 'CET-4',
        level: 'B2',
        theme: '环境·塑料污染（经典话题）',
        text: `Plastic is a wonderful material, and that is exactly the problem. It is cheap, light, strong and waterproof, so we use it for everything from food packaging to phone cases. But plastic does not disappear. Left in the environment, it breaks into smaller and smaller pieces while the total amount never really goes away, and much of it ends up in the ocean, where it is swallowed by fish and birds.

The numbers are difficult to ignore. Environmental groups estimate that millions of tonnes of plastic enter the seas every year, and microplastics, tiny fragments smaller than a grain of rice, have been found in drinking water, sea salt and even rain. Researchers are still studying what these particles do to the human body, but no scientist claims they are harmless.

Governments have started to act. Many countries have banned free plastic bags in supermarkets, and some have restricted single-use items such as straws, cups and cutlery. China's ban on some disposable plastics, introduced in stages, has pushed restaurants and delivery platforms to develop alternatives. Such rules change behaviour quickly: when shoppers must pay for a bag, they soon learn to bring their own.

Yet regulation alone will not solve the problem, because companies still design products that are used for five minutes and last for five hundred years. Campaigners argue that producers, not just consumers, should take responsibility. If a package cannot be reused or recycled easily, they say, it should not be produced in the first place.

Individuals still matter. Carrying a water bottle, refusing unnecessary packaging, and sorting rubbish correctly are small acts, but they send a message to shops and manufacturers about what customers value. The fight against plastic will be won not by one great solution, but by thousands of small daily decisions.`
    },
    {
        id: 'cet4-08',
        title: 'Learning Beyond the Classroom',
        tag: 'CET-4',
        level: 'B2',
        theme: '教育·在线学习（2025 热点：AI 进课堂）',
        text: `The classroom has changed, and not just because of computers. Today a student in a small town can watch a university lecture from another continent, practise a foreign language with an app, or ask an AI tutor to explain a difficult equation at two in the morning. Education no longer stops at the school gate.

Online learning brings obvious advantages. It is flexible, allowing people to study at their own speed and repeat lessons they do not understand. It is also cheaper in many cases, since digital courses avoid the costs of buildings and travel. During holidays, motivated students use such platforms to prepare for exams, and busy adults use them to learn new skills without giving up their jobs.

But the picture is not entirely bright. Teachers warn that many students click through video lessons without really thinking, and that the instant answers provided by AI tools can become a shortcut that replaces understanding. A student who has never struggled with a problem may never learn how to solve one. Moreover, online courses have very high drop-out rates, because without a teacher watching, discipline is easy to lose.

Researchers who compare the two modes offer a balanced conclusion: the best learning often combines them. Schools that assign careful preparation at home and use class time for discussion, experiments and personal help get better results than schools that simply replace lessons with videos. The technology works best when it supports human teachers instead of replacing them.

Perhaps the deepest change is in attitude. In the past, education was something that happened for a few years at the beginning of life. Now it is something that must continue for a lifetime, and the tools to make that possible are in every pocket. The question is no longer whether we can learn; it is whether we will keep choosing to.`
    },
    {
        id: 'cet4-09',
        title: 'Music and the Driver\'s Attention',
        tag: 'CET-4',
        level: 'B1',
        theme: '科技·分心驾驶（2025 热点：热门专辑与事故率）',
        text: `Most drivers agree that music makes the journey better. A favourite song can wake up a tired driver on a long road, and singing along with friends is part of the fun of a road trip. But a surprising 2025 study suggests that music can also be dangerous, especially when it is new.

Researchers noticed that traffic accidents often rise sharply after the release of a hugely popular album. The explanation is not that the music itself is bad, but that drivers want to hear the new songs immediately. They reach for their phones to find the album, read the song list while driving, and keep changing tracks until they find one they like. Each of these actions takes the eyes off the road for several seconds, and at high speed, a few seconds are enough for disaster.

The problem, experts explain, is not music but choice. When we listen to something we know well, we set it and forget it. New music demands attention: we must search, select, skip and adjust the volume. Streaming services make the matter worse by adding recommendations, notifications and playlists, all designed to keep us touching the screen.

The advice from safety experts is simple and practical. First, prepare the playlist before the engine starts. Second, set the phone to a driving mode that blocks notifications. Third, if a song you really want to hear appears, pull over somewhere safe and deal with it there. Finally, never believe that you are the exception: research shows that nearly every driver believes he or she can handle distractions better than others, and nearly every one of them is wrong.

Music will always be part of driving, and that is a good thing. The secret is to let the music play and keep both hands on the wheel and both eyes on the road.`
    },
    {
        id: 'cet4-10',
        title: 'When the Rain Doesn\'t Come',
        tag: 'CET-4',
        level: 'B2',
        theme: '气候·极端天气（2025 热点：英国干旱）',
        text: `For months, the reservoirs of southern England held little more than mud. Gardens turned brown, rivers slowed to streams, and farmers watched their crops suffer. When the rain finally returned, people celebrated in the streets — but water experts warned that the danger was not over. One wet season, they said, does not end a drought.

Drought is a slow disaster. It does not arrive with a crash like an earthquake, and it does not make the evening news as often as a flood. But its effects spread quietly: drinking water becomes precious, food prices rise, and wildlife disappears from drying rivers. In recent years, parts of Europe, Africa and Asia have all experienced unusually long dry periods, and scientists connect many of them to rising global temperatures.

The strange truth about drought is that heavy rain can make it worse. After a long dry spell, the ground becomes hard as stone, so sudden rain cannot enter the soil. It rushes across the surface, carrying soil into rivers, and sometimes causes floods in the very regions that were dying of thirst. Even worse, the rain that does fall may be lost before it can refill the underground water stores that cities depend on.

What can be done? Water experts list several practical measures: fixing the pipes that lose a fifth of their water before it reaches homes; collecting rainwater from roofs; using clever irrigation that waters crops only when they truly need it; and designing gardens with plants that survive with little water.

The deeper lesson is about habits. Water is so cheap and so easy to get that we rarely think about it, until the tap runs dry. Every city, every family, should ask a simple question: if the rain did not come for another year, would we still have enough? The answer, for most of us, is no — and that is a warning worth taking seriously.`
    },
    {
        id: 'cet4-11',
        title: 'Pets in the City',
        tag: 'CET-4',
        level: 'B1',
        theme: '社会·城市养宠（经典话题）',
        text: `The dog on the subway platform sits calmly beside its owner, wearing a small coat against the cold. The cat in the apartment next door has its own bed, toys and a camera that films it during the day. In modern cities, pets have moved from the yard to the centre of family life, and the pet industry has grown into a business worth billions.

Why do city people love animals so much? Researchers point to loneliness as the main reason. Many young adults live alone in small apartments, far from their families, and a pet offers steady company in a way that messages and video calls cannot. A dog forces its owner outside twice a day, creating exercise, fresh air and even new friendships with other dog walkers. For older people, a cat's quiet presence can reduce the feeling of isolation after retirement.

But city life is not naturally friendly to animals. Apartments are small, parks are limited, and work hours are long. Many owners must leave pets alone for the whole day, which is stressful for animals that are used to company. Veterinarians report rising cases of obesity in indoor cats and of anxiety in dogs left home alone. Responsible ownership, they say, means thinking honestly about whether you have time, money and space for an animal before bringing one home.

Cities are slowly adapting. New apartment buildings include pet washrooms and green roofs, companies allow employees to bring dogs to work, and many parks now have special areas where dogs can run free. Some cities have even created "cat cafes", where people who cannot keep pets can spend time with cats instead.

The relationship between cities and pets will keep changing, but one thing seems certain: as long as people need comfort and company, animals will find a place beside us. The challenge is to make that place a good one — for both sides.`
    },
    {
        id: 'cet4-12',
        title: 'A Part-Time Job at College',
        tag: 'CET-4',
        level: 'B1',
        theme: '教育·兼职与学业（经典话题）',
        text: `Walk into almost any campus coffee shop and you will find students behind the counter, balancing cups in one hand and textbooks in the other. Part-time work has become a normal part of university life, and students' opinions about it are sharply divided.

Supporters list the benefits without hesitation. A part-time job provides money, which means independence from parents and the ability to buy books, clothes or plane tickets home. It teaches skills that lectures cannot: talking to customers, managing time, and dealing with difficult people. Employers consistently say they value such experience, and many graduates find that their part-time record gives them an advantage in job interviews. For international students, work can even be the fastest way to improve language skills.

Critics, however, point to the risks. University years are short, and every hour spent serving coffee is an hour not spent in the library or the laboratory. Studies show that students who work more than fifteen hours a week often see their grades fall, and that tired students are more likely to miss classes and sleep poorly. Some students take jobs out of financial necessity rather than choice, and for them the pressure is doubled.

The most sensible position, say education researchers, is neither to praise nor to forbid, but to plan. A job related to one's major can be excellent preparation for a future career; an unrelated job is most valuable in small doses. The students who manage best treat work as a scheduled subject: fixed hours, clear limits, and a firm rule that exams and deadlines come first.

College is a time to learn two kinds of lessons: those from books and those from life. A part-time job offers the second kind, provided the student does not let it destroy the first.`
    },
    {
        id: 'cet4-13',
        title: 'Eating Well on a Budget',
        tag: 'CET-4',
        level: 'B1',
        theme: '健康·饮食与消费（经典话题）',
        text: `"Healthy food is too expensive." It is a complaint heard in every canteen and every student dormitory, and on the surface it seems true. Fresh fruit costs more than instant noodles, and a salad in a café can cost as much as a full meal. Yet nutritionists insist that eating well on a small budget is not only possible; it is often a matter of knowing where the money goes.

The first secret is to cook at home. A bowl of noodles with an egg and some vegetables costs a fraction of the price of the same dish in a restaurant, and the home version contains less oil and salt. Sharing cooking duties with roommates divides the cost and the work. Many students discover that cooking is also a social activity, and that a kitchen shared with friends produces better dinners than any delivery app.

The second secret is to choose the right foods. Nutritionists recommend eggs, beans, soya products and frozen vegetables as cheap sources of protein and vitamins. Frozen vegetables, surprisingly, are often fresher than "fresh" ones that have travelled for days in trucks. Whole grains such as oats and brown rice fill the stomach for a long time, preventing the midnight hunger that leads to expensive snacks.

The third secret is planning. Shopping with a list prevents the impulse buys placed at eye level in supermarkets, where the most profitable and least healthy products live. Buying in season makes fruit and vegetables cheaper, and cooking larger amounts on weekends provides ready meals for busy weekdays.

The real cost of cheap fast food, nutritionists remind us, is paid later, in hospital bills and lost energy. A student who learns to eat well on a small budget gains a skill that will save money and protect health for the rest of his or her life.`
    },
    {
        id: 'cet4-14',
        title: 'The Kindness of Strangers',
        tag: 'CET-4',
        level: 'B1',
        theme: '社会·陌生人善意（经典话题）',
        text: `Lost in a foreign city with a dying phone, you ask a stranger for directions. Instead of pointing, she walks you to the station, waiting with you until the right train arrives. Small acts like this happen every day, yet they rarely appear in the news. Researchers who study kindness say these ordinary moments matter more than we think — for both sides.

Why do people help strangers? Scientists have found that helping others activates the same pleasure centres of the brain as eating or winning a prize. Evolution may have shaped us this way: in ancient times, groups whose members helped each other survived better than groups of pure self-interest. Whatever the reason, the "helper's high" is real, and studies show that people who perform small acts of kindness report greater happiness and even better health.

Kindness also spreads. Psychologists describe a "pay it forward" effect: a person who receives help is significantly more likely to help someone else later the same day. In this way, one small act can travel through a city like a wave. Experiments have measured the effect: when one driver pays for the coffee of the car behind, the chain often continues through many cars.

Of course, kindness has its limits. We are naturally more helpful to people we recognise, and less helpful when we are in a hurry. City life, with its crowds and anonymity, makes it easy to walk past a fallen cyclist or a confused tourist. The question is not whether kindness is natural, but whether we choose to practise it.

The researchers' advice is refreshingly simple: start small. Hold the door, give up your seat, help someone with a heavy suitcase. You may never know how far the effect travels, but the evidence suggests it travels further than you think.`
    },
    {
        id: 'cet4-15',
        title: 'Keeping Heritage Alive',
        tag: 'CET-4',
        level: 'B2',
        theme: '文化·非遗传承（2025 热点：非遗与年轻人）',
        text: `In a workshop in the old city, a young woman in her twenties bends over a piece of paper, scissors moving in patterns her grandmother taught her. Paper-cutting is one of China's traditional arts, and for years people worried that it would die with the older generation. Now, surprisingly, it is coming back to life — thanks to short videos, campus clubs and a new generation that finds beauty in the past.

The revival is part of a larger trend. Across China, interest in intangible cultural heritage, from embroidery and shadow puppetry to traditional tea-making and folk music, has grown rapidly. Young people film craftsmen at work, try the skills themselves, and wear traditional clothing on holidays. Museum visits have risen sharply, and festivals that were once considered old-fashioned now attract crowds of students.

What changed? Experts point to identity. In a fast-changing world, young people look for something stable to belong to, and tradition offers roots. Social media plays a part: a five-minute video of a master creating a delicate paper dragon can reach millions of viewers, turning a local craft into a national sensation. Economic opportunity matters too — crafts that were once hobbies can now earn money through online sales.

Yet preserving heritage is not the same as freezing it. The most successful craftspeople adapt: they use modern materials, design for modern homes, and teach through short courses that busy people can actually attend. Some traditions change so much that purists complain, but most experts accept that a living tradition must breathe.

The deeper lesson is about attention. Heritage survives when enough people care, and care begins with noticing. The grandmother's scissors and the teenager's camera are not enemies; they are partners in the same conversation across time.`
    },
    {
        id: 'cet4-16',
        title: 'Reading Habits in the Smartphone Age',
        tag: 'CET-4',
        level: 'B2',
        theme: '教育·阅读习惯（经典话题）',
        text: `The average smartphone owner checks the device more than a hundred times a day. Between messages, short videos and endless news, the day fills with reading — yet many people complain that they have "no time for books". The puzzle is real: we read more words than ever before, but fewer of us finish a single book a year.

Reading on screens is not the same as reading on paper, and the difference is not only about eyesight. Scientists have found that people reading the same text on paper remember it better and understand difficult passages more deeply than those reading on a screen. The physical book offers fixed pages that the mind can map: readers remember that the important argument was on the left page near the top, and this spatial memory helps them recall the content. Scrolling, by contrast, makes every page look the same.

There is also the matter of attention. A paper book offers a quiet, linear experience; a phone offers a doorway to everything. One notification is enough to pull a reader out of a novel and into a world of messages, leaving the book half-finished. Researchers call this the "attention economy": apps are designed to keep us switching, and switching is the enemy of deep reading.

The good news is that reading habits can be rebuilt. Many former readers say the trick is environment: leave the phone in another room, read for twenty minutes before bed, or join a reading group where finishing the book is a social promise. Libraries report that borrowing is rising again among students, and audiobooks have introduced reading to people who never had time for it.

Deep reading is a skill like any other: it strengthens with practice and weakens with neglect. The phone will always be there, but the choice of what we give our attention to remains ours.`
    },
    {
        id: 'cet4-17',
        title: 'The Magic of Museums',
        tag: 'CET-4',
        level: 'B1',
        theme: '文化·博物馆热（2025 热点：文博游）',
        text: `On a rainy weekend, the queues outside the city museum stretch around the corner. Visitors wait patiently, phones ready to photograph the famous bronze vessel behind its glass case. Ten years ago, such a scene was rare; today, museum visits have become one of the most popular forms of leisure in China, especially among young people.

Why the sudden enthusiasm? Part of the answer is quality. Many museums have redesigned their exhibitions with lights, sounds and digital screens that bring history alive. A visitor can now watch a thousand-year-old painting explain itself, or see a tomb complex rebuilt in three dimensions. Another part is social: sharing photos of beautiful exhibitions on social media has turned the museum visit into a fashion, and special exhibitions of famous works sell out within hours.

Museums offer something that shopping streets cannot: depth. In a world of quick entertainment, a gallery forces a slower pace. Standing before a real object from another era, visitors often describe a strange feeling of connection — the same sunlight fell on this cup, the same hands held it. No screen can reproduce that experience, which is why the photographs people take home rarely capture what they felt.

Educators welcome the trend but add one caution. A museum is not a theme park, and its purpose is not only to be photographed. Curators hope visitors will read a label or two, wonder about the people who made the objects, and come back with questions. The best museums, they say, leave you with more questions than answers.

The popularity will probably continue, and that is good news for history, for education and for the cities that invest in culture. After all, a society that loves its past is more likely to build a thoughtful future.`
    },
    {
        id: 'cet4-18',
        title: 'Small Talk: The Art of Easy Conversation',
        tag: 'CET-4',
        level: 'B1',
        theme: '社会·社交沟通（经典话题）',
        text: `The lift doors open, and a stranger steps in. For thirty seconds, silence fills the small space. Should you say something? Many people avoid small talk entirely, considering it shallow and meaningless. But communication researchers argue that this "meaningless" chatter is one of the most useful social skills we have.

Small talk is the warm-up for all deeper relationships. Every friendship, every business cooperation, every romantic story begins with a few unremarkable sentences about the weather, the traffic or the weekend. These exchanges are not deep, and that is precisely their function: they are safe, low-risk signals that say, "I am friendly, I am not a threat, and I am willing to communicate." Anthropologists note that all human societies, however different, have some version of this ritual.

The benefits are measurable. Studies show that people who chat briefly with baristas, neighbours or fellow passengers feel less lonely and report a better mood for the rest of the day. In workplaces, teams that exchange casual conversation cooperate more effectively, because small talk builds the trust that formal meetings cannot.

So why do so many of us avoid it? Fear is the main reason: the worry of being boring, of mispronouncing a name, or of standing in an awkward silence. Psychologists suggest a simple cure — preparation. Have a few safe topics ready: the weather, food, local news, travel. Ask questions that cannot be answered with a single word, such as "What brings you here today?" People enjoy talking about themselves, so the easiest small talk is usually the one that lets the other person do the talking.

The next time a lift stops and a stranger smiles, try a simple hello. You may learn something, make a friend — or at worst, have a slightly warmer trip to the sixth floor.`
    },
    {
        id: 'cet4-19',
        title: 'The Price of Fast Fashion',
        tag: 'CET-4',
        level: 'B2',
        theme: '环境·快时尚消费（2025 热点：服装浪费）',
        text: `A T-shirt that costs less than a bowl of noodles. A dress worn twice and thrown away. Fashion today moves faster than ever: new styles arrive every week, prices keep falling, and wardrobes keep growing. Environmental researchers call this system "fast fashion", and they are increasingly worried about what happens when the clothes are done with us.

The numbers tell the story. The clothing industry uses enormous amounts of water — a single cotton T-shirt can require thousands of litres to produce — and produces a large share of the world's carbon emissions. More seriously, most discarded clothes do not get recycled. They end up in rubbish mountains in developing countries, or in the sea, where synthetic materials slowly break into microplastics that enter the food chain.

Why do we buy so much? Psychologists point to the pleasure of novelty: a new item gives a small emotional lift, but the feeling fades quickly, so we need another one. Social media intensifies the cycle by showing endless images of people in new outfits, creating the impression that our own wardrobe is outdated. The industry knows this well and designs clothes to go out of style quickly.

Change is slow but visible. Second-hand shops and clothing exchange events have become fashionable among students, and some brands now offer repair services or take back old clothes. A growing number of young consumers say they think twice before buying, asking whether they really need the item and whether it will survive more than one season.

The fashion industry will not change overnight, and individual choices alone cannot fix the problem. But every purchase is a vote: when enough customers reward quality and durability, companies will follow the money. The cheapest shirt, in the end, may be the one that still fits next year.`
    },
    {
        id: 'cet4-20',
        title: 'Why Cities Need More Trees',
        tag: 'CET-4',
        level: 'B1',
        theme: '环境·城市绿化（经典话题）',
        text: `On a hot afternoon, stand on a street without trees, and the heat seems to rise from every surface. Walk two blocks to a tree-lined avenue, and the difference is immediately noticeable: cooler air, softer light, a quieter sound. Cities around the world are rediscovering that trees are not decoration — they are infrastructure.

The benefits of urban trees are well documented. Their leaves cool the air through evaporation, reducing the "heat island" effect that makes cities several degrees hotter than the surrounding countryside. They absorb rainwater, slowing floods during heavy storms. They filter dust and pollution, and their shade protects people, especially children and the elderly, from the summer sun. Studies have even found that hospital patients recover faster when their windows face trees, and that neighbourhoods with more green space report lower crime and greater social contact.

Yet many cities are losing trees faster than they plant them. New roads and buildings replace old avenues, and a single hot, dry summer can kill thousands of mature trees whose roots never had enough space. The trees most valuable to a city are the oldest ones, and they cannot be replaced quickly — a fifty-year-old tree takes fifty years to grow again.

Experts recommend a simple priority: protect what exists before planting what is new. City plans should treat large trees as assets, like pipes and power lines, and give them the same careful management. Planting should favour native species that survive local conditions with little water, and new buildings should be designed around the trees they find on site.

A city with many trees is cooler, cleaner, calmer and healthier. It is also more beautiful, and beauty is not a small thing in a place where people spend most of their lives. Planting a tree may be the cheapest investment a city can make in its own future.`
    },
];

export const CET6_ARTICLES = [
    {
        id: 'cet6-01',
        title: 'Artificial Intelligence and the Future of Work',
        tag: 'CET-6',
        level: 'C1',
        theme: '科技·AI 与就业（2025 热点：AI 智能体）',
        text: `In 2025, the word "agent" acquired a new meaning. Beyond spies and estate brokers, it now describes software that can plan, book, write and negotiate on behalf of its user: an AI agent that arranges a business trip from a single sentence, or a virtual assistant that handles customer complaints without a human supervisor. As these systems become more capable, the oldest question of the automation debate returns with fresh urgency: what will happen to human workers?

History offers both comfort and warning. Every wave of industrial automation destroyed jobs and created new ones: the tractor displaced farmhands but built the food industry, and the spreadsheet reduced bookkeeping jobs while multiplying financial analysis. Economists call this the "displacement effect" versus the "creation effect", and so far the two have roughly balanced. The difference this time is speed and breadth: AI affects not only physical labour but also the white-collar tasks of writing, translating, designing and coding, which were once considered safely human.

The realistic picture is not one of sudden mass unemployment but of rapid reshaping. Routine tasks within every profession are the most exposed: a lawyer who spends hours reading contracts, a teacher who writes the same feedback dozens of times, a doctor who takes notes during consultations. Studies suggest that a large share of working time across occupations could be automated with current technology, yet only a small fraction of jobs face complete replacement. The likely future is augmentation — humans and machines sharing work, with humans supplying judgment, empathy and accountability.

The policy challenge follows automatically. If productivity rises but the rewards concentrate among those who own the technology, inequality will widen, and societies will face difficult choices about training, taxation and social support. Education systems must shift from memorising facts, which machines now do better, to fostering the skills machines lack: critical thinking, communication and creative problem-solving.

The debate, in the end, is not about whether AI will change work — it already has. The question is whether we will redesign work around human strengths, or allow technology to dictate the shape of our lives. The answer, as with most human choices, will be decided by the priorities we set today.`
    },
    {
        id: 'cet6-02',
        title: 'Inside the Brain-Computer Interface',
        tag: 'CET-6',
        level: 'C1',
        theme: '科学·脑机接口（2025 热点：Neuralink 人体试验）',
        text: `For a patient paralysed by illness, the ability to move a cursor with thought alone sounds like science fiction. Yet in 2025, brain-computer interfaces, devices that read neural signals and translate them into commands, moved firmly from laboratory curiosity to commercial reality. A company's implant, roughly the size of a coin, has allowed several patients to control computers, play chess and even communicate faster than they could with eye-tracking technology. The technology works; the harder questions are just beginning.

The principle is elegant. Neurons communicate through electrical pulses, and an implant with fine threads placed in the motor cortex can record those pulses. Machine-learning algorithms learn which patterns of activity correspond to which intended movements, then map them to screen commands. With practice, patients report that using the device becomes almost effortless, like moving a limb they had forgotten they owned.

The medical potential is immense. Researchers hope the same approach can restore speech for patients who have lost it, control robotic limbs, and eventually treat conditions such as depression and epilepsy through targeted stimulation. Clinical trials are expanding, and the cost of the technology, while still high, is falling as the hardware shrinks.

But the ethical questions multiply faster than the patents. Brain data is the most intimate data that exists: it reveals not only what we do but, in some readings, what we feel and intend. Who owns that data, and who can access it? Can an employer require an employee to wear a device that monitors attention? And if a thought-controlled system makes a mistake that causes harm, is the responsibility the patient's, the company's or the algorithm's? Regulators in several countries are drafting rules, but the technology is moving faster than the law.

The most profound issue may be identity itself. When a machine can decode our intentions, the boundary between self and tool blurs. Scientists are careful to say that today's devices read movement intentions, not private thoughts — but the trajectory is clear. Society has perhaps a decade, while the technology is still young and expensive, to decide what it wants the relationship between brain and computer to be.`
    },
    {
        id: 'cet6-03',
        title: 'Carbon Neutrality: A Promise and a Challenge',
        tag: 'CET-6',
        level: 'C1',
        theme: '气候·碳中和政策（2025 热点：COP30）',
        text: `In November 2025, world leaders gathered in Belém, Brazil, for the thirtieth UN climate conference, the first held in the Amazon region. The location was deliberate: the great rainforest, often called the lungs of the planet, stood as both symbol and warning. Behind the speeches and the declarations lay a harder arithmetic: the nations of the world have promised to reach net-zero carbon emissions by mid-century, yet current policies are nowhere close to delivering that promise.

The concept of carbon neutrality sounds simple: emit no more greenhouse gases than we remove. In practice, it splits into two tasks of very different difficulty. The first is reducing emissions — replacing coal plants with wind and solar farms, electrifying transport, and making factories and buildings efficient. This part is well understood, and the costs of solar and battery technology have fallen so dramatically that in many regions renewable energy is now cheaper than fossil fuel.

The second task is harder and less discussed: the "net" part of net-zero. Some emissions, such as those from cement production and long-distance aviation, are extremely difficult to eliminate. To balance them, we must remove carbon from the atmosphere, either by planting forests or by using machines that capture carbon directly from the air. Both approaches remain expensive and unproven at scale, and relying on future technologies is, as one negotiator put it, "borrowing against an account that may never be opened".

The debate extends beyond engineering into fairness. Developing countries argue that the industrialised world, which burned most of the carbon in the atmosphere over two centuries, owes the largest share of the cost. The richest nations pledged long ago to contribute to adaptation funds; the money has arrived slowly and incompletely. Meanwhile, the countries most exposed to rising seas and failing harvests are often the least responsible for the problem.

Climate scientists do not claim the task is easy, only that the alternative is worse. Every fraction of a degree of warming avoided saves lives, coastlines and economies. The gap between promise and policy is real, but so is the progress: renewable energy, electric vehicles and public awareness have all transformed in a single decade. Whether the world closes that gap will be decided by whether governments treat the climate not as one issue among many, but as the condition of all the others.`
    },
    {
        id: 'cet6-04',
        title: 'Humanoid Robots Leave the Laboratory',
        tag: 'CET-6',
        level: 'B2',
        theme: '科技·人形机器人（2025 热点：机器人量产）',
        text: `The video made headlines around the world in 2025: a two-legged robot, built in a Chinese laboratory, sprinting a hundred metres in under ten seconds — faster than any human being. The achievement was partly a publicity stunt, but it pointed to something real. Humanoid robots, machines shaped roughly like people, have moved from research projects to factory floors, warehouses and showrooms, and manufacturers are talking seriously about mass production.

Why build robots that look like us? Engineers offer practical answers. The world's workplaces — stairs, doors, tools, vehicles — were designed for human bodies. A machine with two arms, two legs and five-fingered hands can use the same infrastructure without expensive redesigns. Factories that employ people can add robots without rebuilding their layouts. And, perhaps most importantly, a human-like machine is easier for humans to trust and work beside; experiments show that people communicate more naturally with a robot that mirrors human gestures.

The progress has been driven by the same forces that advanced AI: better sensors, cheaper computing and, above all, neural networks trained on enormous amounts of movement data. The remaining challenges are practical rather than theoretical. Batteries still limit working time; hands remain less dexterous than human hands; and the software that manages balance, perception and decision-making together still makes occasional, unsettling errors. Costs are falling but remain high, and the business case is strongest in repetitive, physically demanding jobs where labour is scarce.

The social questions are familiar from earlier waves of automation but sharper in form. A robot that resembles a person invites emotional responses: people name them, worry about them and sometimes refuse to switch them off. If machines take over care work, will the elderly receive genuine comfort or efficient service? And if robots become cheap labour at scale, will wages for physical work collapse before new roles emerge?

Historians of technology remind us that every major invention was overestimated in the short term and underestimated in the long term. The humanoid robot will probably follow the same curve. What is no longer in doubt is the direction of travel: the machines are here, they are improving quickly, and the society that ignores them will be designing itself for a past that no longer exists.`
    },
    {
        id: 'cet6-05',
        title: 'Quantum Computing: The Race Is On',
        tag: 'CET-6',
        level: 'C1',
        theme: '科技·量子计算（2025 热点：算力竞赛）',
        text: `Ordinary computers think in bits: switches that are either on or off, one or zero. Quantum computers think in qubits, which can be both at once, thanks to a strange property of quantum physics called superposition. Add entanglement, the ability of particles to influence each other across distance, and you have a machine that explores many possibilities simultaneously. For certain problems, the advantage over classical computers is not a matter of degree but of kind.

The most famous potential application is cryptography. The encryption that protects online banking, messaging and government secrets rests on the difficulty of factoring large numbers — a task that would take a classical computer longer than the age of the universe. A sufficiently powerful quantum computer could break this encryption in hours, which explains why nations are racing not only to build the machines but to develop "post-quantum" encryption that the new computers cannot crack.

Other applications are equally transformative. Quantum simulation could model molecules exactly, accelerating the discovery of drugs and new materials, including better batteries for the energy transition. Optimisation problems — routing delivery fleets, scheduling power grids, training certain AI models — could be solved far more efficiently. Researchers caution, however, that most of these promises remain theoretical: today's quantum machines are small, error-prone and extremely sensitive to heat and vibration, and the path from laboratory milestones to useful computation is longer than press releases suggest.

The competition has a geopolitical dimension. Governments on three continents are funding national quantum programmes, treating the technology as strategically important as semiconductors. The talent pool is small, the supply chains are fragile, and the measurement of progress — what counts as "quantum advantage" — is itself contested. Some researchers warn that hype is outpacing hardware; others reply that the same was said of early computers, and that the trajectory, not the current state, is what matters.

The honest summary is that quantum computing is a technology of certain importance and uncertain timing. It will not replace the laptop on your desk, but it may quietly protect, or threaten, the digital world that laptop depends on. The race is real; the finish line is not yet visible.`
    },
    {
        id: 'cet6-06',
        title: 'Editing Genes, Editing Futures',
        tag: 'CET-6',
        level: 'C1',
        theme: '科学·基因编辑伦理（经典话题+2025 进展）',
        text: `The scissors are molecular, the cut is precise, and the consequences can last generations. Gene-editing tools such as CRISPR allow scientists to locate and modify specific stretches of DNA, and the technology has transformed biology in less than a decade. Clinical trials are now treating blood diseases and inherited blindness, and agricultural researchers are editing crops for drought resistance and better nutrition. The promise is enormous; so is the ethical burden.

The first and least controversial use is in the body of a single patient. Editing a patient's own cells, removed, corrected and returned, offers hope for thousands of genetic diseases that medicine could previously only manage. Because the changes affect only that individual, most ethicists accept this use, provided the risks are properly tested. Successes in sickle-cell disease, where a one-time treatment has freed patients from lifelong pain, have turned the debate from "whether" to "how fast".

The second category — editing embryos — changes the rules entirely. Here the edited DNA passes to future generations, and errors would echo through a family line. When a scientist announced in 2018 that he had edited human embryos that were later born as twins, the scientific community responded with outrage and new international agreements, and the experiment is now widely regarded as a boundary violation. Yet the underlying question did not disappear: if editing could remove a fatal disease from a family's future, who should decide whether it is allowed?

Beyond medicine lies the slippery territory of enhancement. If we can edit genes to prevent illness, could we edit them for height, memory or resistance to ageing? Critics warn of a new inequality, where the wealthy purchase biological advantages for their children, and of a quiet change in how society views disability and human variation. Proponents reply that humans have always sought to improve their condition, and that banning all editing would abandon real patients to protect against hypothetical dystopias.

Every transformative technology carries a version of this dilemma, but gene editing is unique because it changes the actors themselves. The debate is not between science and morality but between two visions of responsibility: one that fears the power, and one that fears the cost of leaving it unused. History offers no clear precedent, which is precisely why the conversation matters.`
    },
    {
        id: 'cet6-07',
        title: 'Who Do You Trust Online?',
        tag: 'CET-6',
        level: 'B2',
        theme: '媒体·虚假信息（2025 热点：AI 深度伪造）',
        text: `A video of a world leader announcing a war; a photograph of a disaster that never happened; a voice message from a relative asking for money — all of them entirely fake, and all of them nearly impossible to distinguish from reality. The tools for creating convincing falsehoods, once the province of film studios, are now free to download. The age of generative AI has made "seeing" and "believing" different things, and societies are only beginning to work out the consequences.

The scale of the problem is difficult to measure but easy to sense. Researchers who monitor disinformation report that AI-generated images, audio and video now circulate widely in every major crisis, adding noise and confusion to already chaotic events. The effect is not only that people are deceived; it is also that they stop trusting everything. When any video can be fake, the real evidence becomes suspect, and the liar's best strategy is not to convince you of a lie but to make you doubt every truth.

Why are we so vulnerable? Psychologists point to the "truth bias" — the brain's automatic tendency to accept what we see and hear. Verifying information requires effort, while believing is effortless. Social media amplifies the problem by rewarding speed and emotion over accuracy, and algorithms serve us content that fits our existing beliefs, where even a clumsy fake finds a willing audience.

The solutions under discussion are many and none is complete. Technology companies are developing watermarks and detection systems, though the arms race between creation and detection is one-sided: it is easier to make a fake than to prove one. Platforms are labelling AI-generated content, but labels assume honest producers. Education, many researchers argue, is the most durable defence: teaching students to ask who made this, why it is here, and what evidence exists outside the image itself. Several countries have introduced media literacy into school curricula, treating critical reading as a basic skill on a par with mathematics.

Trust, the scholars remind us, is not the opposite of doubt; it is the product of careful doubt. A society that cannot agree on what is real cannot make decisions, and an electorate that suspects everything will believe anything. The technology will keep improving; the defence must improve faster.`
    },
    {
        id: 'cet6-08',
        title: 'The Silver Economy',
        tag: 'CET-6',
        level: 'C1',
        theme: '社会·银发经济（2025 热点：人口老龄化）',
        text: `By the middle of this century, one in every four people in East Asia will be over sixty-five. The statistics are familiar and alarming in equal measure, and for years they were read as pure bad news: fewer workers, higher pension costs, overburdened hospitals. Lately, however, a different reading has emerged. The ageing of society is also creating the "silver economy" — a vast market for goods and services designed around older lives, and a growing source of jobs, innovation and investment.

The numbers justify the term. Older adults control a disproportionate share of household wealth in most developed economies, and their spending patterns differ sharply from those of the young. They travel outside the school holidays, buy better shoes rather than more shoes, and spend heavily on health, comfort and company. Financial planners estimate the global market for products and services for the over-sixties in the trillions, and companies are reorganising entire departments to serve it: hotels with lower beds, smartphones with larger text, retirement communities with swimming pools and art studios.

The deeper opportunity is technological. The combination of sensors, artificial intelligence and the internet of things has produced a wave of "age-tech": homes that detect a fall within seconds, watches that call an ambulance before the wearer can, robots that remind patients to take medication and converse with those who live alone. Japan, which reached the demographic turning point earlier than anyone else, leads in these innovations, and its experience offers a preview for the rest of the region. Care, long considered a low-tech human service, is becoming a hybrid industry of people and machines.

The critics' objections are not frivolous. The silver economy, they note, serves those with money; the poor elderly remain as invisible as ever. And the shift of care from family to market raises questions that markets answer badly: can a subscription service replace the presence of a daughter, or a robot the warmth of a grandchild? The industry's defenders concede the point and reply that the alternative is often loneliness rather than love — that for many older people, a well-designed service is the difference between independence and institutional care.

Demography is not destiny, but it is arithmetic. The societies that adapt early, treating longevity as an opportunity rather than a burden, will enjoy advantages their competitors cannot copy. The silver economy is not a forecast; it is already the fastest-growing customer group in the world.`
    },
    {
        id: 'cet6-09',
        title: 'A Generation Under Pressure',
        tag: 'CET-6',
        level: 'B2',
        theme: '健康·青少年心理（2025 热点：全球心理健康报告）',
        text: `The data is consistent across continents and cultures: rates of anxiety and depression among young people have risen sharply over the past decade, and the increase is not explained by better diagnosis alone. The World Health Organization has described mental health as one of the defining health challenges of the century, and educators, parents and governments are asking the same urgent question: why is a generation with more comfort, more freedom and more opportunity than any before it also the most distressed?

The explanations offered by researchers fall into several overlapping categories. The first is social media. The average teenager now spends hours daily in a stream of curated images of other people's achievements, holidays and friendships, and the comparison is unfavourable: studies link heavy use of image-based platforms with lower self-esteem and higher rates of sleep disturbance. The second is pressure: in education systems where a single exam can decide a life path, anxiety is a rational response to high stakes, and competition intensifies as family expectations meet economic uncertainty. The third is connection: despite being more "connected" than ever, many young people report having fewer close friends they can truly confide in, and the skills of friendship — patience, forgiveness, face-to-face conversation — atrophy through disuse.

The consequences are measurable. University counselling services report waiting lists months long; rates of self-harm and eating disorders have risen in many countries; and teachers describe a classroom atmosphere of quiet exhaustion. Economists add a long-term cost: a generation that develops chronic mental illness in adolescence carries the burden into working life, reducing productivity and increasing disability.

The responses are as varied as the causes. Schools are introducing well-being lessons and later start times, based on evidence that sleep is the cheapest mental health intervention available. Digital regulations in some countries restrict the addictive features of apps aimed at children. Psychologists emphasise the protective power of a few simple factors: regular exercise, adequate sleep, trusted adults, and the feeling of contributing to something beyond oneself.

The harshest truth is that there is no single villain and no single cure. A generation raised to compare itself with everyone will always find itself lacking, and no policy can fully replace the slow, unglamorous work of listening. But the recognition itself is progress: the first step toward helping a generation in distress is to stop dismissing its distress.`
    },
    {
        id: 'cet6-10',
        title: 'The Great Energy Transition',
        tag: 'CET-6',
        level: 'B2',
        theme: '能源·可再生能源转型（2025 热点：光伏与储能）',
        text: `For most of human history, energy was simple: you burned something — wood, coal, oil — and used the heat. The twenty-first century is replacing that simplicity with something more complex and more fragile: an electricity system built from wind, sun, water and batteries. The transition to renewable energy is the largest infrastructure project ever attempted by our species, and its successes and difficulties both deserve attention.

The successes are real and recent. Solar panels have become so cheap that in many regions new solar power is the least expensive electricity ever generated, cheaper than coal or gas without any subsidy. Wind farms, both on land and at sea, now supply a significant share of electricity in dozens of countries, and electric vehicles have moved from curiosity to mainstream in a single decade. China, in particular, has become the world's largest manufacturer of solar panels, batteries and electric vehicles, driving down costs for the entire planet.

The difficulties are equally real. The sun does not shine at night and the wind does not always blow, so a renewable grid needs storage at a scale that batteries are only beginning to provide. The grid itself must be rebuilt: power now flows from thousands of distributed generators rather than a few central plants, requiring smarter controls and new transmission lines that are slow to plan and expensive to build. And the transition has a geography of winners and losers: communities that depended on coal mines or oil fields face economic loss, and the minerals needed for batteries — lithium, cobalt, copper — are concentrated in a handful of countries, creating new dependencies that resemble the old ones.

The policy challenge is to manage speed and fairness together. Too slow a transition locks in the damage of climate change; too fast a one leaves workers and regions behind, breeding the political backlash that stalls progress. Most economists now agree on the outlines of a solution: price carbon emissions honestly, so that polluting pays; invest the revenue in the transition and in training; and treat the goal not as sacrifice but as modernisation.

Energy is the largest single force shaping the climate, and the climate is the largest single force shaping our future. The transition will not be smooth, and it will not be finished in our lifetimes. But for the first time in history, the cheap option and the clean option are the same option — and that, in the end, is what makes the great transition possible.`
    },
    {
        id: 'cet6-11',
        title: 'The New Space Race',
        tag: 'CET-6',
        level: 'C1',
        theme: '太空·月球基地与太空经济（2025 热点）',
        text: `For thirty years after the end of the Cold War, human spaceflight seemed to be winding down: the Moon visits stopped, the shuttle was retired, and astronauts flew only to a single ageing space station. The 2020s changed the story completely. Nations and private companies are now racing toward the Moon and beyond, with a difference that would have startled the engineers of the last century: much of the money is private, and much of the talk is about commerce.

The Moon is the focus of the current phase. Several countries have landed robotic probes on the lunar surface in recent years, China's Chang'e programme has returned samples from the far side, and both Chinese and American plans call for permanent crewed bases in the 2030s. The stated purposes — science, exploration, national prestige — are familiar, but the new element is the assumption of extraction: water ice in the polar craters could be split into hydrogen and oxygen for rocket fuel, and rare minerals could one day justify mining operations. The Moon, in this vision, is a filling station and a factory rather than merely a destination.

The economics remain speculative. Launch costs have fallen dramatically thanks to reusable rockets, which made the whole industry rethink its assumptions, but building a lunar base remains vastly more expensive than building a research station in Antarctica, with none of the logistical ease. The serious money so far is in Earth orbit: satellite constellations for communication and observation are genuine businesses, space tourism has begun, and the space economy's total value is already measured in hundreds of billions.

The governance question follows the money. The international treaties that govern space were written when only two nations could reach orbit, and they are vague about property rights, resource extraction and the behaviour of private actors. Who owns the water a company extracts from a crater? What rules apply when a mining accident spreads debris? Diplomats are negotiating, but history suggests that law follows practice, and practice is moving fast.

The deeper argument for space exploration has never been economic. Every previous age of exploration returned more than gold: new knowledge, new tools, new ways of seeing the home planet. The photographs of Earth from the Moon changed environmental consciousness; the early space programme's miniaturised technology changed daily life. The enthusiasts of today's race say the same returns await, if we have the patience to look. The sceptics reply that we should fix the planet before escaping it. Both are right, and the balance between them will be settled in the next decade.`
    },
    {
        id: 'cet6-12',
        title: 'Trade Wars and the Cost of Everything',
        tag: 'CET-6',
        level: 'B2',
        theme: '经济·关税与贸易摩擦（2025 热点：美加关税）',
        text: `In the spring of 2025, negotiators from two friendly neighbours sat across a table discussing eggs and cars. When the talks collapsed, new taxes on billions of dollars of goods took effect within hours, and the price of a dozen eggs rose in shops on both sides of the border. The episode was small by the standards of the great trade conflicts of recent years, but it illustrated a general truth: tariffs, once considered a relic of an older economy, have returned as an everyday tool of politics — with consequences that reach into every household.

The theory of tariffs is simple: a tax on imported goods makes them more expensive, protecting domestic producers from foreign competition. The practice is more complicated. Domestic producers may gain, but consumers pay more, and the industries that use imported parts — car factories, electronics assemblers, food processors — face higher costs that they pass on in prices or absorb in lost jobs. Economists have repeatedly found that the costs of tariffs are paid mainly by the importing country's own households and firms, in the form of higher prices and reduced choice.

Why, then, do governments keep using them? The political logic is different from the economic logic. Tariffs are visible and can be announced with a dramatic press conference; the resulting price increases are invisible and arrive months later, spread across thousands of products. They also serve as negotiating tools: threatened tariffs can force partners to open markets or change policies on everything from technology to farm standards. In an era of heightened competition between major economies, the tariff has become a symbol as much as an instrument.

The response of the global economy has been adaptation rather than collapse. Companies have moved supply chains to avoid the taxes, sometimes at great cost; some goods have simply become more expensive; and a few countries have been pushed toward producing more for themselves, a process that brings new industries but also new inefficiencies. The system of global trade rules that prevented such conflicts for decades has weakened, and no new set of rules has clearly replaced it.

The lesson for ordinary citizens is to look past the slogans. Trade policy is not an abstraction; it is the price of a phone, the range of fruit in a supermarket, the survival of a factory town. When leaders speak of winning a trade war, it is worth remembering the older wisdom: in trade, as in most contests, both sides pay for the fight.`
    },
    {
        id: 'cet6-13',
        title: 'Thawing Ground, Rising Risks',
        tag: 'CET-6',
        level: 'C1',
        theme: '气候·永久冻土（2025 热点：热浪与冻土解冻）',
        text: `Beneath the northern reaches of Russia, Canada and Alaska lies a silent giant: permafrost, ground that has remained frozen for thousands of years. It covers roughly a quarter of the northern hemisphere's land, and for most of human history it was an inert curiosity. Now the giant is waking up. Rising temperatures are thawing the frozen ground, and scientists warn that the consequences will reach far beyond the Arctic.

The most immediate danger is physical. As permafrost melts, the land above it loses its foundation. Roads buckle, pipelines twist and break, and buildings tilt at unsettling angles; entire villages in Siberia and Alaska have had to be moved as the ground beneath them turned to mud. The cost of Arctic infrastructure is rising steeply, and engineers are being forced to redesign everything from airport runways to oil installations for a landscape that is no longer stable.

The second danger is atmospheric, and it is the reason the thaw concerns the whole planet. Frozen ground stores enormous quantities of organic matter — the remains of plants and animals locked in ice for millennia. When it thaws, microbes begin to decompose that material and release carbon dioxide and methane, a greenhouse gas many times more powerful than carbon dioxide in the short term. The process is self-reinforcing: warming releases greenhouse gases, which cause more warming, which thaws more ground. Researchers have documented emissions increasing year by year, and models disagree only on how fast the release will be, not whether it will happen.

The third dimension is biological and economic. Diseases frozen in the ground for centuries — anthrax spores, and possibly others — have been revived by thawing, and public health authorities are studying the risk. Meanwhile, the thaw is paradoxically opening new opportunities: shipping routes through the Arctic Ocean now operate in summer, and mineral wealth once locked in ice becomes accessible. The same thaw that destroys infrastructure creates the access that tempts further industrialisation, in a cycle that climate scientists view with alarm and some northern communities view with hope.

There is no engineering solution to a thaw of this scale; the only meaningful intervention is to slow the warming itself. The permafrost, scientists like to say, is a sleeping giant, and the world has been gently shaking its shoulder. The question is whether we choose to let it sleep.`
    },
    {
        id: 'cet6-14',
        title: 'Water: The Coming Crisis',
        tag: 'CET-6',
        level: 'C1',
        theme: '环境·水资源危机（经典话题+2025 数据）',
        text: `It covers seventy percent of the planet, falls freely from the sky, and flows from taps for less than the price of a phone call. No wonder water seems inexhaustible. Yet the numbers tell a different story: nearly half the world's population lives in areas of water stress for at least part of the year, groundwater levels are falling beneath the great agricultural plains of Asia and America, and the UN warns the gap between demand and supply will widen as populations grow and climates change.

The paradox of water is that the total amount never changes. The water on Earth today is the same water the dinosaurs drank; the problem is distribution, timing and quality. Climate change is redrawing the map of rainfall: some regions receive more intense storms and floods, others longer droughts, and the glaciers that supply rivers for hundreds of millions of people are shrinking decade by decade. Meanwhile, the same water must do more: agriculture, industry, energy production and cities all compete for it.

Agriculture consumes the largest share — roughly seventy percent of the water used by humans — and much of it is wasted. Traditional flood irrigation loses most of its water to evaporation and runoff, while drip systems that deliver water to plant roots can save half or more. The economics of water, however, discourage efficiency: in most places it is so cheap that there is no incentive to save it, and farmers who invest in modern irrigation must do so while competitors with wasteful methods face no penalty.

Cities face a different challenge. Urban water systems in many countries lose a fifth or more of their supply to leaking pipes, and the cost of repairing century-old infrastructure is enormous. Water pricing, the most effective conservation tool, is politically explosive, since water is universally regarded as a basic right that should not be denied to the poor. The practical answer, most engineers agree, is tiered pricing: a cheap basic allowance for every household, with steeply rising prices for use beyond it.

The deeper problem is governance. Water does not respect borders: more than half of the world's population lives in river basins shared by several countries, and tensions over rivers are already visible on three continents. The history of water conflicts suggests cooperation usually wins — but only when institutions are built before the crisis, not during it. Water, the saying goes, will be to the twenty-first century what oil was to the twentieth: a source of wealth, of conflict and of innovation. The difference is that there is no substitute for water.`
    },
    {
        id: 'cet6-15',
        title: 'When Companies Promise to Do Good',
        tag: 'CET-6',
        level: 'B2',
        theme: '商业·企业社会责任（经典话题）',
        text: `A supermarket chain announces that all its packaging will be recyclable by 2030. A clothing brand promises to pay its garment workers a living wage. An energy company, whose main business is still fossil fuel, runs advertisements praising wind power. The vocabulary of corporate responsibility has become universal: almost every large company now publishes sustainability reports, appoints ethics officers and talks about its "mission" as warmly as any charity. The question, increasingly asked by consumers, investors and regulators, is how much of this is substance and how much is decoration.

The case for corporate responsibility rests on both morality and pragmatism. Morally, the argument is that large companies hold enormous power over workers, communities and the environment, and power brings obligations. Pragmatically, reputation is an asset: customers prefer trusted brands, talented employees choose employers with values, and investors treat environmental and social performance as indicators of future risk. A factory that pollutes its river, the reasoning goes, will eventually pay the cleanup, the fines and the customers it loses.

The sceptical view is equally well developed. Critics point to "greenwashing", the practice of advertising environmental virtue while continuing the practices that cause the harm, and note that corporate sustainability reports are written by the same departments that write marketing. The deeper critique is structural: companies must legally maximise returns to shareholders, so responsibility is acceptable only when it costs little. When the two goals conflict, the law, not the mission statement, decides.

The response of the system has been to create measurement. Independent rating agencies now score companies on environmental and social criteria, and these scores affect investment decisions worth trillions. Governments have begun to require disclosure: the European Union now forces large companies to report their environmental and social impacts in a standardised format, and other jurisdictions are following. The effect has been to move the debate from "do you care?" to "show your numbers", which is harder to fake — though, as any accountant knows, numbers can be arranged.

The honest conclusion is that corporate responsibility is real, partial and contested. It has changed the behaviour of companies that previously ignored all criticism, and it has failed to change the behaviour of those where the incentives to pollute or exploit are strongest. Consumers who want to know the truth can start with simple questions: what does the company's own report say, who audits it, and what happens to a manager who misses the target? The companies that answer clearly are, in general, the ones that deserve the trust.`
    },
    {
        id: 'cet6-16',
        title: 'The Global Weight-Loss Boom',
        tag: 'CET-6',
        level: 'C1',
        theme: '健康·减肥药经济（2025 热点：GLP-1 药物）',
        text: `Few drugs in history have entered the public imagination as quickly as the new generation of weight-loss medications. Originally developed to treat diabetes, these drugs — known as GLP-1 receptor agonists — mimic a natural hormone that regulates appetite and blood sugar, and their effect on weight is dramatic: patients in clinical trials lose an average of fifteen percent of their body weight or more. Demand has exploded, the companies that make the drugs have become among the most valuable in the world, and economists have begun to calculate the consequences for everything from restaurant menus to health insurance.

The medical significance is difficult to overstate. Obesity is one of the largest public health burdens on the planet, linked to heart disease, diabetes, joint problems and dozens of cancers, and for decades the treatment options were limited to diets that failed and operations that were costly and risky. A medication that produces real, sustained weight loss could prevent disease on a scale comparable to the discovery of antibiotics — if the questions around it can be answered.

Those questions are serious. The first is safety: the drugs' long-term effects are simply not known, and reports of muscle loss, digestive side effects and psychological changes have prompted regulators to require ongoing studies. The second is access: at their current price, the drugs are affordable mainly in wealthy countries and by wealthy patients, raising the possibility that they will widen rather than narrow health inequality. The third is the boundary of use: as healthy people take the drugs to lose a few kilograms, doctors ask where treatment ends and enhancement begins, and whether a society that medicates appetite is solving a problem or avoiding one.

There is also the economic ripple. Analysts have noted that if large numbers of people eat less, the food industry — from snack makers to fast-food chains — will feel the effect, and hospitals may face lower long-term demand for obesity-related surgery. The industry itself is responding: companies are developing cheaper versions, oral forms and next-generation drugs, and the price is expected to fall as competition arrives.

The wisest perspective may be the historical one. Every major medical advance — antibiotics, vaccines, cholesterol drugs — was first celebrated, then questioned, then absorbed into normal practice, with its problems managed rather than eliminated. The weight-loss boom will probably follow the same path. The drugs are not magic, and they are not a substitute for the deeper social causes of obesity. But for millions of people struggling with their weight, the arrival of a tool that actually works is, whatever its limits, a genuine turning point.`
    },
    {
        id: 'cet6-17',
        title: 'Preparing for the Next Pandemic',
        tag: 'CET-6',
        level: 'C1',
        theme: '健康·全球卫生安全（2025 热点：埃博拉疫情）',
        text: `In the summer of 2025, an outbreak of Ebola in the Democratic Republic of Congo became the country's deadliest on record, spreading for months before an effective response was assembled. The disease was contained, but the episode carried an uncomfortable message: the world's defences against epidemics, built at great cost after the last global health crisis, remain incomplete, and the next pandemic is not a question of "if" but of "when".

The advances of the last five years are real. Vaccine technology that once took a decade to develop now works in months; messenger-RNA platforms can be reprogrammed quickly for new threats; and surveillance networks, genetic sequencing and international coordination have all improved. During the Congo outbreak, vaccines and treatments that did not exist during earlier Ebola crises were deployed within weeks, and the death rate among treated patients was far lower than in previous outbreaks. The system, in other words, is better than it was — and still not good enough.

The gaps are structural. The first is funding: epidemic preparedness is expensive in peacetime and invisible when it works, so governments chronically underinvest, and the budgets rise only when the crisis has already begun. The second is equity: the tools of prevention — tests, vaccines, treatments — were distributed unequally during the last pandemic, and the same pattern repeats: wealthy countries order supplies first, poorer countries wait. The third is the nature of the threat itself: the pathogens that worry scientists most — new influenza strains, coronaviruses, antibiotic-resistant bacteria — can emerge anywhere, and a health system's weakest link determines the world's risk.

There is also a political dimension that public health experts are reluctant to discuss but cannot ignore. During the last pandemic, trust in science itself became a casualty: misinformation spread faster than the virus, and measures that public health officials considered simple — masks, distance, vaccination — became sources of conflict. A vaccine that no one will take is not a defence, and rebuilding public trust in health institutions is now recognised as part of preparedness.

The honest summary is that the world has learned many of the technical lessons of the last pandemic and few of the social ones. The machines are better; the will is still fragile. Every year without a major outbreak is an opportunity to strengthen the system, and history suggests such opportunities are not always taken. The next pandemic will test not only our laboratories but our priorities.`
    },
    {
        id: 'cet6-18',
        title: 'How Your Brain Learns',
        tag: 'CET-6',
        level: 'C1',
        theme: '科学·学习神经科学（经典话题）',
        text: `Every student knows the frustration: a page read three times leaves no trace, while a single vivid story stays for decades. The difference is not intelligence but mechanism. Neuroscience has begun to explain why some learning sticks and some dissolves, and the findings carry practical lessons for anyone who has ever sat in a classroom.

The brain learns by strengthening connections between neurons, a process called synaptic plasticity. When information is encountered once, the connections form weakly and fade quickly — which is why cramming the night before an exam produces knowledge that evaporates within days. When the same information is recalled at intervals, the connections are rebuilt each time, becoming physically stronger, and the memory becomes durable. This is the science behind "spaced practice": reviewing material after a day, then a week, then a month, produces far better retention than reviewing it all at once.

The second discovery concerns the role of forgetting. Researchers have found that the brain does not simply store information like a hard drive; it predicts. When we struggle to recall something and then succeed, the act of retrieval itself strengthens the memory more than rereading does. Testing, in this view, is not merely measurement but a learning tool: students who quiz themselves learn more than students who only reread, even when the tests are ungraded. The counter-intuitive implication is that difficulty is a feature, not a bug — the effort of retrieval is what builds the trace.

The third finding is about context and emotion. Memories are encoded together with the environment and mood in which they were formed, which is why material learned in the same room where it will be tested is recalled slightly better, and why emotional material — whether exciting or fearful — is remembered so vividly. Sleep plays a unique role: during deep sleep, the brain replays the day's learning and consolidates it, which is why pulling an all-nighter before an exam is one of the least effective strategies ever invented.

The practical conclusion of all this research is almost embarrassingly simple: learn less at a time, repeat more over time, test yourself rather than rereading, and sleep properly. None of this is new advice, but the neuroscience explains why the old advice works. The brain is not a container to be filled but a muscle to be trained — and like a muscle, it grows not during the workout but during the rest that follows.`
    },
    {
        id: 'cet6-19',
        title: 'Flying Taxis Over the City',
        tag: 'CET-6',
        level: 'B2',
        theme: '科技·低空经济（2025 热点：eVTOL 适航）',
        text: `For a century, the helicopter has been the only flying vehicle that could land on a rooftop, and its cost, noise and maintenance needs have kept it a luxury. Now a new category of aircraft is preparing to change that. Electric vertical take-off and landing vehicles, known as eVTOLs, are small, battery-powered machines with multiple rotors, designed to carry passengers over congested cities. In 2025, several companies received certification to begin commercial operations, and the first scheduled air-taxi routes have opened in a handful of cities. The era of flying taxis has quietly begun.

The technology is less exotic than it sounds. The multiple rotors, like those on a drone, provide both lift and control, and the electric motors are simpler and quieter than helicopter engines. The difficult parts are the ones the public rarely sees: batteries that must be light enough to fly and heavy enough to carry passengers, redundant systems that can keep the aircraft flying if a rotor fails, and the ground infrastructure — landing pads, charging stations, traffic management — that turns a prototype into a service.

The economic promise is appealing. Commuters who spend an hour in traffic could reach the airport in ten minutes; hospitals could move organs across town in minutes; and the cost, while initially high, is expected to fall toward that of a premium taxi as the vehicles are mass-produced. Governments have noticed: several countries have identified the "low-altitude economy" as a growth sector, building test zones and simplifying regulations in a bid to attract the industry.

The challenges are equally clear. Noise, while lower than a helicopter's, is not zero, and residents of flight paths are already objecting. Safety is untested at scale: the vehicles are new, their failure modes are not fully known, and the rules for avoiding other aircraft — and the drones that increasingly fill the same sky — are still being written. The economics are unproven: the early routes are subsidised, and it is far from certain that enough passengers will pay a premium to make the networks profitable. And the social question remains: will flying taxis serve everyone, or only those wealthy enough to leave the traffic behind?

The history of transport suggests that such technologies are rarely stopped by their problems and frequently accelerated by their appeal. The automobile was once a noisy, unreliable curiosity; the aeroplane began with a twelve-second flight. The flying taxi may fail, or it may transform cities as profoundly as the subway did. The next decade will tell which story the sky is writing.`
    },
    {
        id: 'cet6-20',
        title: 'The Future of Money',
        tag: 'CET-6',
        level: 'C1',
        theme: '经济·数字货币（经典话题+2025 进展）',
        text: `Money is one of humanity's oldest inventions and one of its most conservative. Coins minted three thousand years ago would still be recognised as money today, and the basic functions — a store of value, a medium of exchange, a unit of account — have barely changed. Yet the last decade has seen the most radical experiment in the history of money: currencies that exist only as software, created without any government or bank, and exchanged across the internet without intermediaries. The experiment has been turbulent, but it has forced a serious question: what will money look like in the digital age?

The first revolution came from private cryptocurrencies. The technology behind them — the blockchain, a shared ledger maintained by thousands of computers — solved a problem that defeated earlier digital money: preventing the same unit being spent twice without a central authority. The currencies themselves, however, proved too volatile to serve as money in the ordinary sense. A currency whose value can fall by half in a month is a gamble, not a medium of exchange, and even supporters now describe them mainly as stores of value or speculative assets.

The second revolution is arriving from the opposite direction: governments. More than a hundred central banks are studying or testing central bank digital currencies — digital versions of official money combining the convenience of electronic payment with the stability and guarantee of the state. The motivations are varied: some countries want to reach citizens without bank accounts, others want to counter the growth of private cryptocurrencies, a few see an opportunity to make international payments faster and cheaper. The design decisions — whether the currency is anonymous or traceable, interest-bearing or inert — are being debated in central banks around the world, and the choices will shape the financial system for decades.

The social questions are profound. Digital money is programmable: a government could, in principle, create money that expires, can only be spent on certain goods, or loses value when spent too quickly. The same technology that could make payments frictionless could also make surveillance effortless. Privacy, which cash protects by its anonymity, would become a design choice rather than a property of the system.

Money, the historians remind us, is ultimately trust. Coins worked because people trusted the issuing authority; banknotes worked because people trusted the banks; the new digital money will work only if people trust its designers. The technology is the easy part. The difficult question is whether the systems we build will serve the convenience of governments and companies — or the freedom and privacy of the people who use them.`
    }
];
